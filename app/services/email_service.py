"""Transactional email delivery through Resend."""

from html import escape
from urllib.parse import urlencode

import httpx

from app.utils.config import get_settings


class EmailDeliveryError(Exception):
    """Raised when an activation email cannot be accepted by Resend."""


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def send_verification_email(self, email: str, user_id: str, token: str) -> None:
        if not self.settings.resend_api_key:
            raise EmailDeliveryError("Email delivery has not been configured")

        # Keep the secret in the fragment. Browsers do not send fragments to
        # static hosting/CDN access logs or HTTP referrers.
        query = urlencode({"uid": user_id})
        activation_url = f"{self.settings.frontend_url.rstrip('/')}/verify-email?{query}#token={token}"
        escaped_activation_url = escape(activation_url, quote=True)
        logo_url = self.settings.brand_logo_url or f"{self.settings.frontend_url.rstrip('/')}/logo.png"
        escaped_logo_url = escape(logo_url, quote=True)
        subject = "Activate your Diagramwise account"
        text = (
            "Welcome to Diagramwise\n\n"
            "Thanks for creating an account. Confirm your email address to save, "
            "sync, and share diagrams across devices.\n\n"
            f"Activate your account (link expires in {self.settings.email_verification_expire_minutes} minutes):\n"
            f"{activation_url}\n\n"
            "If you did not create a Diagramwise account, you can safely ignore this email."
        )
        # Table-based, inline CSS is deliberate: it renders consistently in
        # Gmail, Outlook, and other clients without external assets.
        html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="x-apple-disable-message-reformatting">
    <title>Activate your Diagramwise account</title>
  </head>
  <body style="margin:0; padding:0; background:#f8f6f1; color:#111827; font-family:Aptos, 'Segoe UI', Arial, sans-serif;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent; mso-hide:all;">Confirm your email to activate your Diagramwise account.</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%; background:#f8f6f1;">
      <tr>
        <td align="center" style="padding:40px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%; max-width:600px;">
            <tr>
              <td style="padding:0 8px 24px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td style="padding:0 12px 0 0; vertical-align:middle;"><img src="{escaped_logo_url}" width="42" height="42" alt="Diagramwise" style="display:block; width:42px; height:42px; border:0; border-radius:10px;"></td>
                    <td style="color:#3730a3; font-size:22px; font-weight:750; letter-spacing:-0.6px; vertical-align:middle;">Diagramwise</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="background:#ffffff; border:1px solid #e5e7eb; border-radius:16px; padding:40px 36px;">
                <p style="margin:0 0 12px; color:#111827; font-size:28px; font-weight:750; letter-spacing:-0.6px; line-height:1.2;">Activate your account</p>
                <p style="margin:0 0 24px; color:#4b5563; font-size:16px; line-height:1.65;">Thanks for creating a Diagramwise account. Confirm your email address to save, sync, and share diagrams across devices.</p>
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 28px;">
                  <tr>
                    <td bgcolor="#4f46e5" style="border-radius:10px;">
                      <a href="{escaped_activation_url}" style="display:inline-block; padding:14px 22px; color:#ffffff; font-size:16px; font-weight:700; line-height:1; text-decoration:none;">Activate account</a>
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 10px; color:#6b7280; font-size:14px; line-height:1.55;">This link expires in {self.settings.email_verification_expire_minutes} minutes and can be used only once.</p>
                <p style="margin:0; color:#6b7280; font-size:14px; line-height:1.55;">If you did not create a Diagramwise account, you can safely ignore this email.</p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 8px 0; color:#6b7280; font-size:12px; line-height:1.55;">
                If the button does not work, copy and paste this link into your browser:<br>
                <a href="{escaped_activation_url}" style="color:#4f46e5; text-decoration:underline; word-break:break-all;">{escaped_activation_url}</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {self.settings.resend_api_key}"},
                    json={"from": self.settings.resend_from_email, "to": [email], "subject": subject, "text": text, "html": html},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmailDeliveryError("Unable to send activation email") from exc


email_service = EmailService()
