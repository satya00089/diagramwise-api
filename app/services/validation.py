"""Validation functions for system design assessments and sharing permissions."""

from app.models.request_models import AssessmentRequest, SystemComponent
from app.models.diagram_models import Permission
from app.services.dynamodb_service import dynamodb_service


def validate_system_components(
    components: list[SystemComponent],
) -> tuple[bool, list[str]]:
    """
    Validate system components for basic architectural principles
    Returns (is_valid, list_of_issues)
    """
    issues: list[str] = []

    if not components:
        return False, ["No components provided for assessment"]

    # Check for essential components
    component_types = {comp.type.value for comp in components}

    # Basic validation rules
    if len(components) < 2:
        issues.append("System design should have at least 2 components")

    # Check for database in data-driven applications
    has_backend = "backend" in component_types
    has_database = "database" in component_types

    if has_backend and not has_database:
        issues.append("Backend service detected but no database component found")

    # Check for load balancer in scalable systems
    if len(components) > 3 and "load-balancer" not in component_types:
        issues.append("Consider adding a load balancer for better scalability")

    # Check for monitoring
    if len(components) > 2 and "monitoring" not in component_types:
        issues.append("Consider adding monitoring components for observability")

    return len(issues) == 0, issues


def validate_connections(request: AssessmentRequest) -> tuple[bool, list[str]]:
    """
    Validate system connections for consistency
    Returns (is_valid, list_of_issues)
    """
    issues: list[str] = []

    if not request.connections:
        return True, []  # No connections to validate

    component_ids = {comp.id for comp in request.components}

    for conn in request.connections:
        # Check if source and target components exist
        if conn.source not in component_ids:
            issues.append(
                f"Connection source '{conn.source}' does not exist in components"
            )

        if conn.target not in component_ids:
            issues.append(
                f"Connection target '{conn.target}' does not exist in components"
            )

    return len(issues) == 0, issues


def validate_sharing_permission(
    user_id: str, diagram_id: str, required_permission: Permission = Permission.READ
) -> tuple[bool, str]:
    """
    Validate if a user has the required permission to access a diagram.

    Returns (has_permission, error_message)
    """
    diagram, permission = dynamodb_service.get_diagram_for_user(user_id, diagram_id)
    if not diagram or permission is None:
        return False, "Access denied: You do not have permission to access this diagram"

    if required_permission == Permission.EDIT and permission == Permission.READ:
        return False, "Access denied: You only have read permission for this diagram"

    return True, ""


def validate_diagram_access(
    user_id: str, diagram_id: str, action: str = "access"
) -> tuple[bool, str]:
    """
    Validate if a user can perform an action on a diagram.

    Returns (can_access, error_message)
    """
    required_permission = Permission.READ
    if action in ["update", "delete", "share"]:
        required_permission = Permission.EDIT

    return validate_sharing_permission(user_id, diagram_id, required_permission)


def validate_collaborator_limit(
    diagram_id: str, owner_id: str, max_collaborators: int = 50
) -> tuple[bool, str]:
    """
    Validate that the diagram hasn't exceeded the maximum number of collaborators.

    Returns (is_valid, error_message)
    """
    collaborators = dynamodb_service.get_diagram_collaborators(diagram_id, owner_id)
    if len(collaborators) >= max_collaborators:
        return False, f"Maximum number of collaborators ({max_collaborators}) exceeded"

    return True, ""
