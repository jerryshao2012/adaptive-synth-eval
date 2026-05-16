from adaptive_synth_eval.config.schemas import Persona


def persona_instruction(persona: Persona) -> str:
    return (
        f"You are a {persona.role} in {persona.location}. "
        f"Seniority: {persona.seniority}. Style: {persona.communication_style}. "
        f"HR familiarity: {persona.hr_familiarity}. Privacy sensitivity: {persona.privacy_sensitivity}."
    )
