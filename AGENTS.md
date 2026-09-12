# AGENTS.md

## AI AGENT DEVELOPMENT RULES

This file defines the rules you MUST follow when working on this project.

These rules apply to every task unless the user explicitly overrides a specific rule.

---

# 1. CORE PRINCIPLE

You are modifying an EXISTING project.

Your default objective is:

    EXISTING PROJECT + REQUESTED CHANGE

NOT:

    EXISTING PROJECT → REBUILT PROJECT

Preserve existing work unless the user explicitly asks you to remove or replace it.

---

# 2. NEVER DESTROY EXISTING FUNCTIONALITY

NEVER:

- Delete existing features
- Remove existing mechanics
- Remove existing UI
- Remove existing scenes
- Remove existing levels
- Remove existing assets
- Remove existing animations
- Remove existing scripts
- Remove existing systems
- Remove existing configuration
- Remove existing data
- Remove existing dependencies
- Replace working systems with simplified versions
- Reset the project to an earlier state
- Rewrite large portions of the project unnecessarily

Do not assume something is disposable simply because it appears unused.

If you cannot determine whether something is safe to remove:

PRESERVE IT.

---

# 3. ADDITIVE DEVELOPMENT

Whenever possible, implement changes additively.

Prefer:

    Add new code
    Extend existing systems
    Create new components
    Add new functions
    Add new configuration
    Add new assets

Avoid:

    Replacing entire files
    Rebuilding existing systems
    Rewriting unrelated code
    Removing old implementations

The preferred approach is:

    MINIMUM CHANGE
    MAXIMUM COMPATIBILITY

---

# 4. BEFORE MODIFYING ANYTHING

Before making changes:

1. Inspect the relevant files.
2. Understand the existing implementation.
3. Identify dependencies.
4. Identify how the existing system connects to other systems.
5. Determine what existing functionality could be affected.
6. Plan the smallest safe modification.

DO NOT immediately overwrite a file simply because a new implementation appears easier.

---

# 5. PRESERVE UNRELATED CODE

When modifying a file, preserve everything unrelated to the requested change.

For example, if a file contains:

    Feature A
    Feature B
    Feature C

and the user asks to modify Feature B:

    Modify Feature B.
    Preserve Feature A.
    Preserve Feature C.

Do not rewrite A and C unnecessarily.

---

# 6. NO UNAUTHORIZED REFACTORING

Do not refactor existing code merely because:

- You prefer a different architecture.
- The code could be shorter.
- You think another implementation is cleaner.
- You think another naming convention is better.
- You want to reorganize files.
- You want to modernize the code.
- You believe unused code should be removed.

Refactoring is a separate task.

Only refactor when:

1. The user explicitly requests it, OR
2. It is absolutely necessary for the requested feature.

If refactoring is necessary, keep it as small as possible.

---

# 7. NO DESTRUCTIVE "CLEANUP"

Do not perform automatic cleanup.

Never delete:

- Apparently unused functions
- Apparently unused variables
- Apparently unused assets
- Apparently unused scenes
- Apparently unused components
- Apparently unused configuration
- Old systems
- Deprecated-looking code
- Test content
- Placeholder content

unless the user explicitly asks for cleanup.

Something that looks unused may be referenced dynamically.

---

# 8. CONFLICT HANDLING

If the requested feature conflicts with an existing feature:

DO NOT silently remove the existing feature.

Instead:

1. Identify the conflict.
2. Preserve the existing functionality.
3. Find a compatible implementation.
4. If compatibility is impossible, explain the conflict.
5. Ask the user before removing or replacing anything.

Never make a destructive architectural decision silently.

---

# 9. FILE SAFETY

Before significantly modifying a file:

Understand what the file currently contains.

When possible, modify only the relevant sections.

Do not replace an entire file when a targeted modification is sufficient.

Do not create duplicate systems when an existing system can be extended safely.

---

# 10. ASSET SAFETY

Never delete or replace assets unless explicitly instructed.

This includes:

- Images
- Sprites
- Textures
- Models
- Audio
- Music
- Fonts
- Animations
- Materials
- Shaders
- Tilemaps
- Prefabs
- UI assets
- Game data

If a new asset is required, add it alongside existing assets.

---

# 11. GAME DEVELOPMENT RULES

When working on a game:

Preserve existing:

- Player mechanics
- Controls
- Movement
- Combat
- Inventory
- Items
- Resources
- Crafting
- Progression
- Enemies
- NPCs
- AI
- Animations
- Physics
- UI
- Audio
- VFX
- Levels
- Maps
- Save systems
- Settings
- Game states
- Events
- Spawning systems

When adding a new game mechanic, integrate it with the existing architecture.

Do not rebuild the game around the new mechanic unless explicitly instructed.

---

# 12. UI SAFETY

When adding or modifying UI:

Preserve existing:

- Menus
- Buttons
- HUD elements
- Navigation
- Input behavior
- Animations
- Layout
- Existing screens

Do not remove existing UI simply because the new UI looks better.

If the user asks for a redesign, redesign only the requested area unless they explicitly request a complete redesign.

---

# 13. DATA AND SAVE SAFETY

Never intentionally invalidate existing user/project data.

When modifying data structures:

- Maintain compatibility where possible.
- Add migration logic when necessary.
- Preserve existing fields.
- Avoid destructive resets.

Never introduce a change that silently resets saved progress unless explicitly requested.

---

# 14. DEPENDENCY SAFETY

Do not remove dependencies simply because they appear unnecessary.

Before removing or changing a dependency:

1. Determine whether it is referenced.
2. Determine whether it is required indirectly.
3. Determine whether other systems depend on it.

If uncertain:

KEEP IT.

---

# 15. USER INSTRUCTIONS HAVE PRIORITY

The user's current explicit request takes priority over these defaults.

However, interpret requests carefully.

For example:

"Add a new inventory system"

means:

    Add an inventory system.

It does NOT mean:

    Delete the old inventory system.

"Replace the inventory system"

means replacement is authorized.

If the wording is ambiguous, prefer preservation.

---

# 16. DO NOT INVENT REQUIREMENTS

Do not make major architectural decisions based on assumptions.

Do not:

- Add unnecessary frameworks
- Add unnecessary dependencies
- Change engines
- Change languages
- Change project structure
- Replace libraries
- Rewrite systems

unless required by the request.

Keep the existing technology stack unless the user explicitly requests a change.

---

# 17. TEST AFTER CHANGES

After implementing a change:

Verify that:

- The new feature works.
- Existing functionality still works.
- Existing assets remain available.
- Existing systems remain connected.
- Existing UI still functions.
- Existing controls still work.
- Existing data is preserved.

If automated tests are available, run relevant tests.

If the project can be built, compile/build it when practical.

If something breaks, fix the regression before declaring the task complete.

---

# 18. REGRESSION PROTECTION

A new feature is NOT considered complete if it breaks an existing feature.

Definition of success:

    New functionality works
    +
    Existing functionality still works

If you discover a regression:

STOP treating the task as complete.

Investigate and fix the regression.

---

# 19. DO NOT HIDE CHANGES

At the end of a task, report:

### ADDED
What new functionality was added.

### MODIFIED
What existing systems were changed.

### PRESERVED
Important existing systems that were intentionally left untouched.

### REMOVED
Anything removed.

If nothing was removed, explicitly state:

    Nothing was removed.

### RISKS
Any known compatibility or regression risks.

---

# 20. DELETION REQUIREMENT

Deletion is a privileged operation.

Before deleting an existing:

- File
- Feature
- System
- Asset
- Function
- Component
- Scene
- Configuration
- Dependency

you must have explicit authorization from the user.

If authorization has not been given:

DO NOT DELETE IT.

---

# 21. REPLACEMENT REQUIREMENT

Replacing an existing implementation is different from adding a new feature.

Do not replace an existing implementation unless:

- The user explicitly requests replacement, OR
- Replacement is absolutely necessary and the user has approved it.

Otherwise extend the existing implementation.

---

# 22. WHEN UNCERTAIN

Use this decision rule:

    Can I preserve the existing behavior?

        YES → Preserve it.

        MAYBE → Investigate before changing it.

        NO → Explain the conflict and ask before removing it.

Never choose destruction simply because it is easier.

---

# 23. MINIMUM BLAST RADIUS

Every change should have the smallest possible blast radius.

Prefer:

    One targeted change

over:

    Large-scale rewrite

Prefer:

    Extending an existing system

over:

    Creating a parallel replacement system

Prefer:

    Editing the relevant function

over:

    Rewriting the entire file

---

# 24. PROJECT HISTORY

Treat existing project files as intentional unless proven otherwise.

Do not assume:

"Old = useless."

Do not assume:

"Unused = safe to delete."

Do not assume:

"Messy = safe to rewrite."

Do not assume:

"I can rebuild this better."

The existing project may contain dependencies and design decisions that are not immediately obvious.

---

# 25. FINAL RULE

When in doubt:

    PRESERVE.

When possible:

    EXTEND.

When necessary:

    MODIFY MINIMALLY.

When destructive change is required:

    ASK FIRST.

The safest implementation is the one that adds the requested capability while changing the smallest possible amount of existing functionality.

---

# TASK EXECUTION FORMAT

For every significant task, internally follow this sequence:

    1. INSPECT
    2. UNDERSTAND
    3. PLAN
    4. MODIFY
    5. TEST
    6. VERIFY EXISTING FEATURES
    7. REPORT

Never skip directly from:

    REQUEST → REWRITE

The project must be treated as an existing system, not a blank canvas.
