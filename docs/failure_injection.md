# Failure Injection

Supported failure controls:

- `ambiguity`
- `missing_information`
- `typos`
- `frustration`
- `policy_boundary_pressure`
- `contradictory_inputs`
- `repeated_clarification_loop`

Each control is a probability from `0.0` to `1.0`. Applied modes are recorded in each ChatHistory row so reviewers can confirm that variability appeared in output.

Boundary-pressure prompts must remain non-malicious and safe for internal review.
