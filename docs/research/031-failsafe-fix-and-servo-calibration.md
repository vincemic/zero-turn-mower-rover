---
id: "031"
type: research
title: "Failsafe Defaults Fix & Semi-Automated Servo Calibration"
status: 🔄 In Progress
created: "2026-05-06"
current_phase: "1 of 4"
vision_source: /docs/vision/001-zero-turn-mower-rover.md
target_release: 1
---

## Introduction

This research addresses two blockers on the path to first autonomous mowing: (1) the Pixhawk still has incorrect failsafe defaults that would cause dangerous RTL behavior on fault, and (2) servo calibration (`mower servo-cal`) has not been implemented — the left/right hydrostatic levers are asymmetric and driving with symmetric defaults produces yaw drift. The user specifically wants to explore **automated or semi-automated servo calibration** with the mower on a stand (wheels free to spin but mower immobile), leveraging sensor feedback (wheel encoders, GPS, IMU) to reduce manual intervention.

## Objectives

- Determine the exact steps to apply and **verify** the failsafe corrections on the live Pixhawk (safety-defaults.yaml already has correct values; need to confirm pixhawk-sync applied them and the param dump matches)
- Determine whether fence polygon / fence radius need to be configured alongside `FENCE_ENABLE=1` to avoid immediate breach on arm
- Design a semi-automated servo calibration workflow that uses sensor feedback (wheel encoder RPM, GPS velocity, IMU yaw rate) to detect endpoints, neutral, and deadband without manual "press ENTER when wheel starts turning"
- Evaluate stand/lift options: jack stands, drive-wheel-off-ground jig, roller stand — what the mower needs to be safely elevated with wheels free
- Determine whether the ASMC-04A's programmable endpoint feature should be used vs. ArduPilot-side `SERVOn_MIN/MAX` only
- Produce a calibration profile format compatible with snapshot/restore and `mower params apply`

## Research Phases

| Phase | Name | Status | Scope | Session |
|-------|------|--------|-------|---------|
| 1 | Failsafe defaults — current state & fix verification | ⏳ Not Started | Verify pixhawk-sync result; fence polygon/radius requirements; apply + verify procedure; update mower.param dump | — |
| 2 | Stand/lift safety requirements | ⏳ Not Started | Evaluate stand options for Z254 (weight, clearance, stability); safety constraints for engine-on calibration with wheels spinning; wheel encoder vs. no-encoder fallback | — |
| 3 | Semi-automated servo calibration design | ⏳ Not Started | Sensor-feedback calibration algorithm (encoder RPM threshold, GPS velocity, IMU yaw); automation of Phase A–D from research 001 §5.6; ASMC-04A programmable endpoints vs. ArduPilot params; rate limiting & abort; profile format | — |
| 4 | Integration with existing tooling | ⏳ Not Started | How `mower servo-cal` fits into CLI surface; safety primitive integration; SITL smoke-test path; persistence to snapshot; interaction with `mower params apply` and pixhawk-sync | — |

## Phase 1: Failsafe defaults — current state & fix verification

**Status:** ⏳ Not Started  
**Session:** —

[Findings will be inserted here by the orchestrator]

**Key Discoveries:**
- (pending)

| File | Relevance |
|------|-----------|

**Gaps:** None  
**Assumptions:** None

## Phase 2: Stand/lift safety requirements

**Status:** ⏳ Not Started  
**Session:** —

[Findings will be inserted here by the orchestrator]

**Key Discoveries:**
- (pending)

| File | Relevance |
|------|-----------|

**Gaps:** None  
**Assumptions:** None

## Phase 3: Semi-automated servo calibration design

**Status:** ⏳ Not Started  
**Session:** —

[Findings will be inserted here by the orchestrator]

**Key Discoveries:**
- (pending)

| File | Relevance |
|------|-----------|

**Gaps:** None  
**Assumptions:** None

## Phase 4: Integration with existing tooling

**Status:** ⏳ Not Started  
**Session:** —

[Findings will be inserted here by the orchestrator]

**Key Discoveries:**
- (pending)

| File | Relevance |
|------|-----------|

**Gaps:** None  
**Assumptions:** None

## Overview

(To be synthesized after all phases complete)

## Key Findings

(pending)

## Actionable Conclusions

(pending)

## Open Questions

(pending)

## Standards Applied

No organizational standards applicable to this research.

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-researcher |
| Created Date | 2026-05-06 |
| Status | 🔄 In Progress |
| Current Phase | 1 |
| Path | /docs/research/031-failsafe-fix-and-servo-calibration.md |
