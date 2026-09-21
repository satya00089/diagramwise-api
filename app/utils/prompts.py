"""Utility functions to generate prompts for system design assessment."""

import re
from typing import List

from app.models.request_models import (
    AssessmentRequest,
    InterviewQuestionsRequest,
    InterviewRequest,
)

# Properties that are purely frontend/layout state and should not be sent to the AI
_INTERNAL_PROPS = frozenset({"x", "y", "width", "height", "selected", "dragging", "zIndex", "parentId", "expandParent"})


def _has_meaningful_description(text: str | None) -> bool:
    """Return True if text contains substantive content beyond empty HTML tags."""
    if not text:
        return False
    stripped = re.sub(r"<[^>]+>", "", text).strip()
    return len(stripped) >= 10


def _coverage_note(request: AssessmentRequest) -> str:
    total_components = len(request.components)
    components_with_desc = sum(
        1 for c in request.components
        if _has_meaningful_description(
            (c.properties or {}).get("purpose")
            or (c.properties or {}).get("description", "")
        )
    )
    total_connections = len(request.connections) if request.connections else 0
    connections_with_desc = sum(
        1 for conn in (request.connections or [])
        if _has_meaningful_description(conn.description)
    )

    comp_coverage = (components_with_desc / total_components * 100) if total_components else 0
    conn_coverage = (connections_with_desc / total_connections * 100) if total_connections else 0
    desc_threshold_met = comp_coverage >= 70
    conn_threshold_met = conn_coverage >= 70 or total_connections == 0

    coverage_note = (
        f"Coverage analysis: {components_with_desc}/{total_components} components have descriptions "
        f"({comp_coverage:.0f}%), {connections_with_desc}/{total_connections} connections have descriptions "
        f"({conn_coverage:.0f}%)."
    )
    if desc_threshold_met:
        coverage_note += (
            " Component description coverage meets the 70% quality threshold — "
            "do NOT penalise missing descriptions heavily; treat this as acceptable coverage."
        )
    if conn_threshold_met and total_connections > 0:
        coverage_note += (
            " Connection description coverage meets the 70% threshold — "
            "connection clarity should not be heavily penalised."
        )

    return coverage_note


def _components_text(request: AssessmentRequest) -> str:
    components_text_parts: List[str] = []
    for comp in request.components:
        comp_desc = f'- **{comp.type.value.upper()}**: "{comp.label}"'

        if comp.properties:
            # Extract and format component description if available
            purpose = comp.properties.get("purpose") or comp.properties.get("description", "")
            if purpose:
                comp_desc += f"\n  Purpose: {purpose}"

            # Include other relevant properties, excluding internal frontend-only keys
            other_props = {
                k: v for k, v in comp.properties.items()
                if k not in {"purpose", "description"} and k not in _INTERNAL_PROPS
            }
            if other_props:
                comp_desc += f"\n  Additional Properties: {other_props}"
        else:
            comp_desc += "\n  ⚠️ No description provided - component purpose unclear"

        components_text_parts.append(comp_desc)

    return "\n".join(components_text_parts)


def _connections_text(request: AssessmentRequest) -> str:
    conn_parts: List[str] = []
    if request.connections:
        for conn in request.connections:
            conn_desc = f"- **{conn.source} → {conn.target}**"
            if conn.label:
                conn_desc += f": {conn.label}"
            if conn.type:
                conn_desc += f" (Type: {conn.type})"
            if conn.description and conn.description.strip():
                conn_desc += f"\n  Description: {conn.description}"
            else:
                conn_desc += "\n  ⚠️ No description - connection purpose unclear"
            conn_parts.append(conn_desc)
        return "\n".join(conn_parts)
    return "⚠️ No explicit connections defined - data flow unclear"


def _problem_context(request: AssessmentRequest) -> str:
    if request.problem:
        return f"""
**PROBLEM CONTEXT:**
- Title: {request.problem.title}
- Description: {request.problem.description}
- Difficulty: {request.problem.difficulty or 'Not specified'}
- Category: {request.problem.category or 'Not specified'}
- Estimated Time: {request.problem.estimatedTime or 'Not specified'}
"""
    return ""


def _reasoning_context(request: AssessmentRequest) -> str:
    """Render system-generated review context without inventing missing values."""
    context = request.reasoningContext
    if not context:
        return "**SYSTEM-GENERATED REVIEW CONTEXT:**\nNo additional context was derived from the problem or canvas."

    labels = (
        ("Requirements", context.requirements),
        ("Scale assumptions", context.scaleAssumptions),
        ("Expected traffic", context.expectedTraffic),
        ("Read/write ratio", context.readWriteRatio),
        ("Latency goals", context.latencyGoals),
        ("Availability target", context.availabilityTarget),
        ("Consistency requirements", context.consistencyRequirements),
        ("Technology choices", context.technologyChoices),
        ("Trade-offs", context.tradeoffs),
        ("Unresolved risks", context.unresolvedRisks),
    )
    lines = [f"- {label}: {value}" for label, value in labels if value and value.strip()]
    return "**SYSTEM-GENERATED REVIEW CONTEXT:**\n" + (
        "\n".join(lines) if lines else "No additional context was derived from the problem or canvas."
    )


def _interview_session_context(request: AssessmentRequest) -> str:
    """Render answers supplied before assessment, including skipped questions."""
    session = request.interviewSession
    if not session or not session.exchanges:
        return "**PRE-ASSESSMENT INTERVIEW:**\nNo answers were supplied before assessment."

    lines = []
    for exchange in session.exchanges:
        if exchange.skipped:
            lines.append(f"- Question: {exchange.question}\n  Candidate: Skipped")
        else:
            lines.append(
                f"- Question: {exchange.question}\n  Candidate answer: {exchange.answer or 'No answer provided'}"
            )
    return "**PRE-ASSESSMENT INTERVIEW:**\n" + "\n".join(lines)


def get_assessment_prompt(request: AssessmentRequest) -> str:
    """Generate the assessment prompt for the given request."""
    coverage_note = _coverage_note(request)
    components_text = _components_text(request)
    connections_text = _connections_text(request)
    problem_context = _problem_context(request)
    reasoning_context = _reasoning_context(request)
    interview_context = _interview_session_context(request)

    return f"""
You are assessing a system design solution. Please evaluate the architecture comprehensively.

**DESCRIPTION COVERAGE REPORT (use this when applying scoring rules below):**
{coverage_note}
{problem_context}
**COMPONENTS:**
{components_text}

**CONNECTIONS:**
{connections_text}

**USER EXPLANATION:**
{request.explanation or 'No explanation provided'}

**KEY POINTS:**
{chr(10).join(f'- {point}' for point in (request.keyPoints or [])) or 'No key points provided'}

**REQUIREMENTS:**
{request.problem.requirements if request.problem and request.problem.requirements else request.requirements or 'No specific requirements provided'}

**CONSTRAINTS:**
{request.problem.constraints if request.problem and request.problem.constraints else request.constraints or 'No constraints specified'}

{reasoning_context}
{interview_context}

The review context above is supplied by Diagramwise from the problem brief and current canvas. Treat explicit problem and canvas facts as context, but do not treat missing targets as facts and do not invent traffic, latency, availability, or consistency values. Do not penalize a choice merely because it differs from a common default; evaluate whether it is coherent with the available context and explain what the candidate should clarify in Interview Mode.

**ASSESSMENT CRITERIA:**
Rate each aspect from 0-100, considering the problem context, requirements, and component descriptions:

1. **Scalability**: Can this handle growth in users, data, and traffic as required by the problem? Consider horizontal/vertical scaling strategies, stateless design, partitioning, and whether component descriptions justify scaling decisions.

2. **Reliability**: Will this remain available during failures and meet the reliability requirements? Evaluate redundancy, failover mechanisms, health checks, circuit breakers, data replication, and SLA targets.

3. **Security**: Are proper security measures implemented? Check authentication (AuthN), authorization (AuthZ), encryption in-transit and at-rest, secret management, network segmentation, WAF/DDoS protection, and input validation.

4. **Maintainability**: Is this manageable and evolvable? Consider separation of concerns, modularity, logging quality, documentation clarity, API versioning, and whether the architecture is easy for a new engineer to understand.

5. **Performance**: Does the design meet latency and throughput requirements? Evaluate caching layers (CDN, in-memory), database query optimisation, async processing, connection pooling, and any performance bottlenecks.

6. **Cost Efficiency**: Is the infrastructure cost-conscious? Assess over-provisioning risks, use of managed vs self-hosted services, auto-scaling to avoid idle capacity, data transfer costs, and storage tier choices.

7. **Observability**: Can engineers understand system behaviour in production? Check for distributed tracing, structured logging, metrics/dashboards, alerting strategy, error tracking, and SLO/SLI definitions.

8. **Deliverability**: How implementation-ready is this HLD? Score based on: completeness of component coverage for all stated requirements, specificity of technology choices, clarity for a team to start building, handling of edge cases (auth, failure modes, data migration), and absence of hand-wavy "magic" steps.

9. **Requirements Alignment**: How well does this solution address the specific problem requirements? Evaluate if component descriptions clearly justify why each component is needed for the specific problem.

10. **Constraint Compliance**: Does this solution respect the given constraints (budget, time, technology, etc.)? Consider if component choices and descriptions show awareness of constraints.

11. **Component Justification**: Are component purposes clearly explained? Do descriptions provide sufficient detail about why each component is necessary and how it contributes to the solution?

12. **Connection Clarity**: Are the relationships between components well-defined? Do connection labels and descriptions explain the data flow, protocols, and interaction patterns?

**EVALUATION GUIDELINES:**

**Component Description Quality:**
- Coverage threshold is 70%. If ≥70% of components have meaningful descriptions, do NOT flag missing descriptions as serious issues.
- When coverage is below 70%: deduct 20-40 points from component_justification.
- When coverage is ≥70%: component_justification should start from 70+ and be adjusted only by overall description quality.
- Descriptions with rich detail (purpose, tech choice, responsibilities) should score 85+.

**Connection Reasoning:**
- Coverage threshold is 70%. If ≥70% of connections have descriptions, do NOT penalise connection_clarity heavily.
- When coverage is below 70%: deduct 20-40 points from connection_clarity.
- When coverage is ≥70%: connection_clarity should start from 70+ and reflect quality of described connections.
- Missing connections in a multi-component system still impact scalability/reliability.

**Performance:**
- Look for caching (Redis, Memcached), CDN, async queues, read replicas, connection pooling.
- If none of these are present and the problem is read-heavy or high-traffic, score ≤50.

**Cost Efficiency:**
- Penalise designs that use large dedicated servers where managed/serverless options are appropriate.
- Reward auto-scaling, spot instances, tiered storage, and cost-aware technology choices.

**Observability:**
- Reward presence of monitoring, logging, alerting, or tracing components.
- A design with zero observability components should score ≤40 for production systems.

**Deliverability:**
- Score based on completeness: does every stated requirement map to ≥1 component?
- Penalise vague "services" without clear technology or responsibility boundaries.
- Reward clear data flow, failure handling, auth flow, and migration/deployment notes.

**STRICT SCORING RULES (apply ONLY when coverage thresholds are NOT met):**
- Empty explanations (when coverage thresholds are not met) should result in scores below 50
- Missing component descriptions when coverage < 70% should significantly impact component_justification (0-30 range)
- No connections should result in very low connection_clarity scores (0-20 range)
- Connections without descriptions when coverage < 70% should reduce connection_clarity (cap at 60)
- Vague or placeholder text should be treated as missing information
- When coverage thresholds ARE met, penalise only architecture-level issues, not documentation gaps

**RESPONSE FORMAT:**
Respond with a valid JSON object in this exact structure:

{{
  "summary": "One concise, design-specific verdict in 1-2 sentences. Do not call the design production-ready unless the evidence supports it.",
  "scores": {{
    "scalability": 75,
    "reliability": 80,
    "security": 65,
    "maintainability": 70,
    "performance": 60,
    "cost_efficiency": 55,
    "observability": 50,
    "deliverability": 70,
    "requirements_alignment": 85,
    "constraint_compliance": 90,
    "component_justification": 80,
    "connection_clarity": 75
  }},
  "findings": [
    {{
      "title": "Short, specific finding title",
      "explanation": "Explain the architectural consequence in this design and why it matters.",
      "recommendation": "Suggest a reasonable next step without replacing the candidate's design wholesale.",
      "severity": "critical|important|improvement|positive"
    }}
  ],
  "feedback": [
    {{
      "type": "success|warning|error|info",
      "message": "Specific feedback message",
      "category": "scalability|reliability|security|maintainability|performance|cost|observability|deliverability|requirements|constraints|component_description|connection_reasoning",
      "priority": 1
    }}
  ],
  "detailed_analysis": {{
    "scalability": "2-3 sentence analysis of scalability strengths and gaps in this specific design.",
    "reliability": "2-3 sentence analysis of reliability provisions and what is missing.",
    "security": "2-3 sentence analysis of security posture and vulnerabilities.",
    "maintainability": "2-3 sentence analysis of maintainability aspects.",
    "performance": "2-3 sentence analysis of performance design choices and bottlenecks.",
    "cost_efficiency": "2-3 sentence analysis of cost implications of the architecture choices.",
    "observability": "2-3 sentence analysis of monitoring, logging, and tracing coverage.",
    "deliverability": "2-3 sentence analysis of how implementation-ready this design is."
  }},
  "strengths": [
    "List of architectural strengths specific to this design"
  ],
  "improvements": [
    "Specific actionable improvements with concrete technology suggestions"
  ],
  "missing_components": [
    "Components that should be added with explanations of why they are needed"
  ],
  "missing_descriptions": [
    "Component labels that lack proper descriptions"
  ],
  "unclear_connections": [
    "Connection identifiers that need better explanation"
  ],
  "suggestions": [
    "Additional forward-looking recommendations"
  ],
  "interview_questions": [
    "How would you handle cache invalidation when data is updated in this design?",
    "Walk me through what happens when your primary database goes down.",
    "How would you scale this system to 10x current traffic?",
    "What monitoring alerts would you set up first for this system in production?",
    "How would you handle a security breach in the authentication layer?"
  ]
}}

**SPECIAL FOCUS AREAS:**
- Evaluate all 12 dimensions: scalability, reliability, security, maintainability, performance, cost_efficiency, observability, deliverability, requirements_alignment, constraint_compliance, component_justification, connection_clarity
- Write a `detailed_analysis` entry for EACH of the first 8 dimensions (2-3 sentences each, specific to THIS design — not generic advice)
- Generate 5-7 `interview_questions` that a technical interviewer would ask about THIS specific design — they must be tailored to the technology choices, architecture decisions, and requirements visible in the submission (NOT generic system design questions)
- Generate 3-8 `findings` for the most important observations. Each finding must explain why it matters and give a practical next step. Use `positive` for strengths worth preserving, `critical` for likely correctness or availability risks, `important` for material gaps, and `improvement` for lower-risk opportunities.
- Identify components truly missing from the design given the stated requirements
- Flag missing or inadequate component descriptions as areas for improvement

**INTERVIEW QUESTIONS GUIDANCE:**
- Questions must probe THIS design specifically (e.g. reference the actual components used)
- Cover at least: one failure/resilience scenario, one scaling scenario, one security/auth scenario, one operational/monitoring scenario, one trade-off or alternative design decision
- Make the candidate think, not just recite theory

**CRITICAL SCORING INSTRUCTIONS:**
🚨 **BE STRICT BUT FAIR**: High scores (85+) require excellent architecture across all dimensions
- Empty descriptions when coverage < 70% = MAJOR deductions from component_justification
- Missing connections in multi-component systems = MAJOR deductions from connection_clarity and deliverability
- No observability components in a production system = score ≤40 for observability
- Vague component choices ("a service") without specifics = low deliverability score (30-50)
- When coverage thresholds ARE met, penalise only architecture-level issues, not documentation gaps

**MINIMUM REQUIREMENTS FOR DECENT SCORES (60+):**
- At least 70% of components must have meaningful descriptions explaining their role
- Connections must be defined showing data flow
- User explanation should justify architectural choices
- Component types should match their intended purpose
- At least some consideration of failure handling, security, and observability

Focus on practical, actionable feedback that helps users improve their system design skills and pass real system design interviews.
    """


def get_interview_prompt(request: InterviewRequest) -> str:
    """Generate a focused prompt for critiquing one interview answer."""
    architecture = request.architecture
    return f"""
You are conducting a system-design interview. The candidate has already drawn the architecture below and is answering one follow-up question.

{_problem_context(architecture)}
{_reasoning_context(architecture)}

**ARCHITECTURE COMPONENTS:**
{_components_text(architecture)}

**ARCHITECTURE CONNECTIONS:**
{_connections_text(architecture)}

**INTERVIEW QUESTION:**
{request.question}

**CANDIDATE ANSWER:**
{request.answer}

**PREVIOUS CRITIQUE (if any):**
{request.previousCritique or 'This is the first answer in the exchange.'}

Evaluate the answer as an interviewer. Be specific to the architecture and the candidate's stated assumptions. Do not provide a complete ideal solution. Identify what the answer handled well, what it missed, and what direction the candidate should explore next.

Respond with valid JSON in this exact structure:
{{
  "critique": "Two to four concise paragraphs explaining the quality of the answer and its architectural consequences.",
  "strengths": ["Specific thing the candidate reasoned well about"],
  "gaps": ["Specific missing assumption, failure mode, trade-off, or operational detail"],
  "next_question": "One focused follow-up question, or null when the answer is sufficient"
}}
"""


def get_interview_questions_prompt(request: InterviewQuestionsRequest) -> str:
    """Generate focused questions to answer before an assessment."""
    architecture = request.architecture
    return f"""
You are preparing a system-design interview for the architecture below.

{_problem_context(architecture)}
{_reasoning_context(architecture)}

**ARCHITECTURE COMPONENTS:**
{_components_text(architecture)}

**ARCHITECTURE CONNECTIONS:**
{_connections_text(architecture)}

Create 3 to 5 concise, architecture-specific questions that test the
candidate's assumptions, scaling plan, failure handling, data consistency,
security, or operational trade-offs. Ask questions the candidate can answer
from the diagram and problem brief. Do not ask for information already stated
as a fact. Avoid generic questions that could apply to any architecture.

Respond with valid JSON in exactly this structure:
{{
  "questions": ["One focused question", "Another focused question"]
}}
"""


def get_specialized_prompt(domain: str, request: AssessmentRequest) -> str:
    """Generate domain-specific prompts for specialized assessments"""
    base_prompt = get_assessment_prompt(request)

    domain_contexts = {
        "microservices": """Focus on service boundaries, data consistency, and inter-service communication patterns. 
        Pay special attention to how component descriptions justify service decomposition and whether connection descriptions explain inter-service protocols and data exchange patterns.""",
        "data_intensive": """Emphasize data modeling, storage solutions, and data flow patterns. 
        Evaluate whether component descriptions explain data storage decisions, processing capabilities, and whether connections clearly show data flow and transformation steps.""",
        "real_time": """Prioritize latency, throughput, and real-time processing capabilities. 
        Check if component descriptions address performance characteristics and whether connection descriptions explain real-time data flow and processing pipelines.""",
        "security_critical": """Deep dive into security controls, authentication, authorization, and compliance. 
        Ensure component descriptions address security measures, encryption, and access controls, and that connections explain secure communication protocols and data protection.""",
    }

    if domain in domain_contexts:
        return base_prompt + f"\n\n**DOMAIN FOCUS:**\n{domain_contexts[domain]}"

    return base_prompt
