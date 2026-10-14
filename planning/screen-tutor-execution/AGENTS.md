# Screen Tutor execution instructions

These instructions apply only inside \`planning/screen-tutor-execution/\`.

Read \`README.md\`, \`BUILD_STATE.json\`, and \`CHECKPOINT.md\` before changing execution records. The immutable plan is at \`C:/Users/redab/OneDrive/Bureau/self learning 24.7 agent/planning/screen-tutor-v2-2026-09-14/START_HERE.md\`. Follow its handoff, work-package dependency graph, specifications, and completion gates.

Never replace live state with the plan's initial \`execution/BUILD_STATE.json\`. Save evidence before accepting a packet. A mock, source inspection, local test, native qualification, provider qualification, human evaluation, and released deployment are different evidence levels. Keep blockers open and continue other eligible work.

The active coordinator owns \`BUILD_STATE.json\` and \`CHECKPOINT.md\`. A delegated packet must name its owned source paths, frozen interfaces, required checks, and returned evidence. Do not run two coordinators against this state.
