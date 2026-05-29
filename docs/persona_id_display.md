# Realtime Persona ID Display and Per-Persona Behavior Enhancement

## Overview

This enhancement adds continuous visibility of the current persona ID during realtime simulation mode by displaying it directly in the interactive control prompt, and enables **per-persona behavior modes** where each persona can maintain its own distinct communication style independently.

## Problem

Previously, users running simulations with `--realtime-chat` and `--interactive-realtime-controls` had no easy way to see which persona was currently active without:
1. Checking the conversation headers (which scroll away)
2. Running the `status` or `s` command manually
3. Remembering which persona they last switched to

## Solution

The interactive prompt now dynamically displays the active persona ID:

**Before:**
```
⚡> 
```

**After (with P001 active):**
```
⚡> [P001] 
```

**After switching to P002:**
```
⚡> [P002] 
```

## Implementation Details

### Core Changes

1. **New Property**: Added `prompt_text` property to `RealtimeChatController` class
   - Location: `src/adaptive_synth_eval/engines/realtime_controls.py`
   - Dynamically generates prompt text based on current `active_persona_id`
   - Returns base prompt (`⚡> `) when no persona is set
   - Returns enhanced prompt (`⚡> [PERSONA_ID] `) when persona is active

2. **Updated Input Loops**: Modified both input loop methods to use dynamic prompt
   - `_input_loop()`: Uses `self.prompt_text` instead of `self.PROMPT_TEXT`
   - `_input_loop_basic()`: Uses `self.prompt_text` instead of `self.PROMPT_TEXT`

3. **Automatic Updates**: The prompt updates automatically because:
   - `prompt_text` is a property that reads `active_persona_id` each time
   - When user switches personas via command, `set_active_persona()` updates the state
   - Next prompt render picks up the new persona ID automatically

### Code Example

```python
@property
def prompt_text(self) -> str:
    """Generate dynamic prompt text that includes current persona ID if available."""
    base_prompt = self.PROMPT_TEXT
    persona_id = self.active_persona_id
    if persona_id:
        return f"{base_prompt}[{persona_id}] "
    return base_prompt
```

## Benefits

1. **Continuous Visibility**: Always visible while typing commands
2. **Immediate Feedback**: Updates instantly when switching personas
3. **Non-Intrusive**: Doesn't clutter the conversation display
4. **Context-Aware**: Shows relevant information right where user interacts
5. **No Breaking Changes**: Backward compatible - works with existing code
6. **Per-Persona Behaviors**: Each persona maintains independent behavior modes that persist across switches

## Testing

Added comprehensive test in `tests/unit/test_realtime_controls.py`:

```python
def test_realtime_controller_prompt_text_shows_persona():
    """Test that the prompt text dynamically includes the active persona ID."""
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)
    
    # Initially, no persona is set
    assert controller.prompt_text == "⚡> "
    
    # Set active persona
    controller.set_active_persona("P001")
    assert controller.prompt_text == "⚡> [P001] "
    
    # Switch to another persona
    controller.set_active_persona("P002")
    assert controller.prompt_text == "⚡> [P002] "
    
    # Clear persona
    controller.set_active_persona(None)
    assert controller.prompt_text == "⚡> "
```

## Usage

The feature works automatically when using interactive realtime controls:

```bash
# Enable realtime chat with interactive controls
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat

# The prompt will show: ⚡> [P001]  (or whichever persona is active)

# Switch personas mid-conversation
persona P002

# Prompt updates to: ⚡> [P002] 
```

### Per-Persona Behavior Modes

Each persona can have its own behavior mode that persists across switches:

```bash
# Set P001 to aggressive mode
⚡> [P001] style aggressive
Behavior updated for P001

# Switch to P002 and set different behavior
⚡> [P001] persona P002
Persona updated
⚡> [P002] style polite
Behavior updated for P002

# Switch back to P001 - retains 'aggressive' behavior
⚡> [P002] persona P001
Persona updated
⚡> [P001] status
Status: delay=0.80s, mode=running, behavior=aggressive, persona=P001
```

**Key Points:**
- `style <mode>` applies to the **currently active persona** only
- Behavior modes are stored per-persona and persist across switches
- When no persona is active, styles apply globally as a fallback
- Status command shows the correct behavior for the active persona

## Files Modified

1. `src/adaptive_synth_eval/engines/realtime_controls.py` - Core implementation (prompt display + per-persona behavior tracking)
2. `src/adaptive_synth_eval/engines/chat_history_simulation.py` - Integration with persona-specific behavior retrieval
3. `tests/unit/test_realtime_controls.py` - Test coverage for both features
4. `docs/cli_usage.md` - Documentation update
5. `README.md` - User-facing documentation
6. `examples/demo_persona_prompt.py` - Demonstration script

## Design Rationale

### Why Show in Prompt?

Several alternatives were considered:

1. **Status Bar**: Would require terminal manipulation libraries
2. **Header Overlay**: Could interfere with conversation display
3. **Periodic Status Messages**: Would clutter the output
4. **Prompt Enhancement** ✓: Simple, always visible, non-intrusive

The prompt approach was chosen because:
- It's already the focus of user attention when typing commands
- No additional UI complexity required
- Works with both `prompt_toolkit` and basic `input()` fallback
- Automatically updates without extra rendering logic

### Why Use a Property?

Using a `@property` decorator ensures:
- Always reflects current state (no stale data)
- No need to manually refresh/update
- Clean separation of concerns
- Easy to test independently

## Future Enhancements

Potential improvements could include:

1. **Color Coding**: Different colors for different personas in the prompt
2. **Persona Role Display**: Show role alongside ID (e.g., `⚡> [P001:new_employee]`)
3. **Behavior Mode Indicator**: Also show current behavior style in prompt (e.g., `⚡> [P001:aggressive]`)
4. **Customizable Format**: Allow users to configure prompt format
5. **Visual Styling**: Apply Rich formatting styles to persona messages based on behavior mode

## Compatibility

- ✅ Works with single-persona mode (shows `[PERSONA_ID]`)
- ✅ Works with multi-persona mode (updates on switch)
- ✅ Works with `--persona` filter flag
- ✅ Compatible with all behavior modes
- ✅ No breaking changes to existing functionality
- ✅ Falls back gracefully if `prompt_toolkit` unavailable
