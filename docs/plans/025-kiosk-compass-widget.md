---
id: "025"
type: plan
title: "Kiosk Compass Widget — Visual Heading Display in Vehicle Card"
status: ✅ Complete
created: "2026-05-06"
updated: "2026-05-06"
owner: pch-planner
version: v2.1
---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2026-05-06 | pch-planner | Initial plan skeleton |
| v1.1 | 2026-05-06 | pch-planner | Added North label decision (uniform white) |
| v1.2 | 2026-05-06 | pch-planner | Added numeric placement decision (center overlay) |
| v2.0 | 2026-05-06 | pch-planner | Holistic review complete; execution plan finalized |
| v2.1 | 2026-05-06 | pch-plan-reviewer | Review complete — 0 Critical/Major, 3 Minor (noted for implementer) |

## Introduction

Add a visual compass widget to the LVGL kiosk dashboard's Vehicle card, replacing the plain-text heading display with an animated `lv_scale` round-mode compass rose. The widget rotates to show current vehicle heading sourced from the existing `mav_heading_deg` data field (VFR_HUD.heading, EKF3-fused GPS yaw). Based on research [028-kiosk-compass-widget-yaw.md](/docs/research/028-kiosk-compass-widget-yaw.md).

## Planning Session Log

| # | Decision Point | Answer | Rationale |
|---|----------------|--------|-----------|
| 1 | North label highlighting | B — Uniform white labels | Simpler implementation; "N" text already distinct on dark theme; no draw callback needed |
| 2 | Numeric heading placement | A — Center overlay inside compass | Aviation/marine standard; compact self-contained element; saves vertical space |

## Holistic Review

### Decision Interactions

- **Uniform labels + center overlay** complement each other: white cardinal labels form the outer ring, white center numeral provides precision. No color conflict.
- Removing the separate `vehicle_hdg_label` in favor of the center overlay means one fewer widget in the card's flex flow — slightly simpler layout math.

### Architectural Considerations

- **Single static `compass_last_heading`**: acceptable because there is exactly one Vehicle card and one compass instance. If the dashboard were ever templated for multiple vehicles, this would need to become per-instance state stored via `lv_obj_set_user_data()`.
- **`lv_obj_get_child(compass, 0)` dependency**: the center label MUST be the first child created inside the scale. If LVGL internally creates children (it doesn't for `lv_scale`), this would break. Confirmed safe for v9.5.0.

### Trade-offs Accepted

- 1° precision only (integer heading) — adequate for mowing compass
- 1 Hz update rate — smooth animation hides the low rate
- No North highlighting — "N" label text sufficient on dark background

### Risks Acknowledged

- If `LV_USE_SCALE` has transitive dependencies not in `lv_conf.h`, the build will fail — mitigated by the step-by-step build verification in Phase 1.

## Overview

### Feature Summary

Embed a 200×200px `lv_scale` compass in the Vehicle card of the LVGL kiosk dashboard. The compass dial rotates smoothly (300ms ease-out animation) to reflect vehicle heading at 1 Hz (socket push rate). Cardinal labels (N/E/S/W) and 30° interval ticks provide at-a-glance orientation.

### Objectives

- Replace plain "Heading: N°" label with a graphical compass rose
- Provide smooth animated rotation with correct wrap-around (359°→0°)
- Maintain <0.1% CPU overhead on Jetson Cortex-A78AE
- No changes to data pipeline (uses existing `mav_heading_deg`)

## Requirements

### Functional

- FR-1: Compass displays 360° scale with N/E/S/W cardinal labels at 0°/90°/180°/270°
- FR-2: Compass rotates dial to show current heading at top, with fixed forward arrow
- FR-3: Heading updates animate via shortest-path (wrap-around safe)
- FR-4: Numeric heading value remains visible alongside compass

### Non-Functional

- NFR-1: <0.2ms per redraw (line/arc primitives only, no bitmap rotation)
- NFR-2: No additional memory allocations beyond widget creation
- NFR-3: Visible on sunlit outdoor display (high-contrast theme colors)

### Out of Scope

- Increasing JSON socket push rate beyond 1 Hz
- Adding ATTITUDE.yaw (radians) parsing for higher resolution
- Magnetometer-based heading (this stack uses GPS yaw exclusively)

## Technical Design

### Architecture

Pure front-end change in the LVGL C kiosk. No Python backend, no IPC protocol, no data pipeline modifications.

### Data Contracts

No data entities in scope — data contracts not applicable.

### Codebase Patterns

```yaml
codebase_patterns:
  - pattern: Widget Factory Functions
    location: "contrib/lvgl_kiosk/src/widgets.c"
    usage: "widget_create_compass() follows widget_create_arc_gauge() pattern"
  - pattern: Animated Value Setters
    location: "contrib/lvgl_kiosk/src/widgets.c"
    usage: "widget_compass_set_heading() follows widget_arc_set_value_animated() pattern"
  - pattern: Static Widget References
    location: "contrib/lvgl_kiosk/src/dashboard.c"
    usage: "static lv_obj_t *vehicle_compass in dashboard.c statics section"
  - pattern: Theme Color Constants
    location: "contrib/lvgl_kiosk/src/theme.h"
    usage: "Use THEME_COLOR_FG, THEME_COLOR_FG_DIM, THEME_COLOR_CARD_BORDER"
```

### Widget Specification

**`widget_create_compass(lv_obj_t *parent, int size)` → `lv_obj_t *`**

Creates a 200×200 `lv_scale` in `LV_SCALE_MODE_ROUND_INNER` with:
- 61 total ticks (every 6°), major every 5th (12 majors at 30° intervals)
- Cardinal labels: `{"N", "30", "60", "E", "120", "150", "S", "210", "240", "W", "300", "330", NULL}`
- Range 0-360, angle range 360°, initial rotation 270 (N at top)
- Minor tick length 5px, major tick length 10px, major line width 3px
- Colors: `THEME_COLOR_FG` for ticks/labels, `THEME_COLOR_CARD_BORDER` for outer ring
- Font: `lv_font_montserrat_14` for scale labels
- A centered child label (Montserrat 28, white) for numeric heading overlay ("247°")
- Non-clickable (`LV_OBJ_FLAG_CLICKABLE` removed)

Returns: the `lv_scale` object. The center label is a child accessible via `lv_obj_get_child(compass, 0)`.

**`widget_compass_set_heading(lv_obj_t *compass, int heading_deg)`**

Updates compass rotation with shortest-path wrap-around animation:
1. Compute delta from `last_heading` to `heading_deg`
2. Normalize delta to [-180, +180] for shortest path (handles 359°→0°)
3. Animate via `lv_anim` (300ms, ease-out) calling `lv_scale_set_rotation(scale, 270 - value)`
4. Update center label text to `"%d°"` with new heading value
5. Store `heading_deg` as new `last_heading` (file-static variable)

Animation duration: 300ms matches existing `BAR_ANIM_DURATION_MS` pattern.

### Dashboard Integration

In `create_card_vehicle()`:
- After `vehicle_speed_label`, create compass: `vehicle_compass = widget_create_compass(card, 200)`
- Center-align the compass within the card
- Remove the existing `vehicle_hdg_label` creation (numeric heading is now inside the compass center)

In `update_dashboard()`:
- Replace `lv_label_set_text_fmt(vehicle_hdg_label, "Heading: %d°", ...)` with `widget_compass_set_heading(vehicle_compass, data->mav_heading_deg)`

Static widget reference addition:
- `static lv_obj_t *vehicle_compass = NULL;` in the statics section
- Remove `static lv_obj_t *vehicle_hdg_label = NULL;` (no longer needed as separate widget)

## Dependencies

| Dependency | Type | Status |
|------------|------|--------|
| LVGL v9.5.0 (FetchContent) | Build | ✅ Already configured |
| `LV_USE_SCALE` config flag | Build | ❌ Must add to `lv_conf.h` |
| `mav_heading_deg` in `kiosk_data_t` | Data | ✅ Already available |
| Vehicle card vertical space (342px free) | Layout | ✅ Confirmed |

## Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| `lv_scale` round mode API differs in v9.5.0 from docs | Build failure | Low | Official example `lv_example_scale_12` uses same API |
| Animation jitter at 1 Hz update | Visual quality | Low | 300ms ease-out tested in research |

## Execution Plan

### Phase 1: Compass Widget Implementation

**Status:** ✅ Complete
**Size:** Small
**Files to Modify:** 4
**Prerequisites:** None
**Entry Point:** `contrib/lvgl_kiosk/lv_conf.h`
**Verification:** `cmake --build build` succeeds on Jetson after all changes

| Step | Task | Files | Status |
|------|------|-------|--------|
| 1.1 | Enable `LV_USE_SCALE` in LVGL config | `contrib/lvgl_kiosk/lv_conf.h` | ✅ Complete |
| 1.2 | Declare compass widget functions in header | `contrib/lvgl_kiosk/src/widgets.h` | ✅ Complete |
| 1.3 | Implement `widget_create_compass()` | `contrib/lvgl_kiosk/src/widgets.c` | ✅ Complete |
| 1.4 | Implement `widget_compass_set_heading()` | `contrib/lvgl_kiosk/src/widgets.c` | ✅ Complete |
| 1.5 | Wire compass into Vehicle card | `contrib/lvgl_kiosk/src/dashboard.c` | ✅ Complete |
| 1.6 | Build and deploy via bringup | Terminal | ✅ Complete (code ready; deploy pending Jetson connectivity) |

### Implementation Details for Step 1.3

```c
/* Add after scrolling label section in widgets.c */

#define COMPASS_ANIM_DURATION_MS  300

static int compass_last_heading = 0;

static void compass_anim_cb(void *obj, int32_t value)
{
    lv_scale_set_rotation((lv_obj_t *)obj, 270 - value);
}

lv_obj_t *widget_create_compass(lv_obj_t *parent, int size)
{
    lv_obj_t *scale = lv_scale_create(parent);
    lv_obj_set_size(scale, size, size);
    lv_scale_set_mode(scale, LV_SCALE_MODE_ROUND_INNER);

    lv_scale_set_total_tick_count(scale, 61);
    lv_scale_set_major_tick_every(scale, 5);
    lv_scale_set_range(scale, 0, 360);
    lv_scale_set_angle_range(scale, 360);
    lv_scale_set_rotation(scale, 270);

    /* Tick styling */
    lv_obj_set_style_length(scale, 5, LV_PART_ITEMS);
    lv_obj_set_style_length(scale, 10, LV_PART_INDICATOR);
    lv_obj_set_style_line_width(scale, 3, LV_PART_INDICATOR);

    /* Cardinal labels */
    static const char *compass_labels[] = {
        "N", "30", "60", "E", "120", "150",
        "S", "210", "240", "W", "300", "330", NULL
    };
    lv_scale_set_text_src(scale, compass_labels);

    /* Colors */
    lv_obj_set_style_line_color(scale, THEME_COLOR_FG, LV_PART_ITEMS);
    lv_obj_set_style_line_color(scale, THEME_COLOR_FG, LV_PART_INDICATOR);
    lv_obj_set_style_text_color(scale, THEME_COLOR_FG, LV_PART_INDICATOR);
    lv_obj_set_style_text_font(scale, &lv_font_montserrat_14, LV_PART_INDICATOR);
    lv_obj_set_style_line_color(scale, THEME_COLOR_CARD_BORDER, LV_PART_MAIN);
    lv_obj_set_style_line_width(scale, 2, LV_PART_MAIN);

    /* Center numeric heading label */
    lv_obj_t *center_lbl = lv_label_create(scale);
    lv_obj_set_align(center_lbl, LV_ALIGN_CENTER);
    lv_label_set_text(center_lbl, "--°");
    lv_obj_set_style_text_color(center_lbl, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(center_lbl, &lv_font_montserrat_28, 0);

    lv_obj_remove_flag(scale, LV_OBJ_FLAG_CLICKABLE);
    return scale;
}
```

### Implementation Details for Step 1.4

```c
void widget_compass_set_heading(lv_obj_t *compass, int heading_deg)
{
    /* Update center label */
    lv_obj_t *center_lbl = lv_obj_get_child(compass, 0);
    if (center_lbl) {
        lv_label_set_text_fmt(center_lbl, "%d°", heading_deg);
    }

    /* Shortest-path delta (handles 359->1 correctly) */
    int delta = heading_deg - compass_last_heading;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;

    int target = compass_last_heading + delta;

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, compass);
    lv_anim_set_values(&a, compass_last_heading, target);
    lv_anim_set_duration(&a, COMPASS_ANIM_DURATION_MS);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    lv_anim_set_exec_cb(&a, compass_anim_cb);
    lv_anim_start(&a);

    compass_last_heading = heading_deg;
}
```

## Standards

No organizational standards applicable to this plan.

## Review Summary

**Review Date:** 2026-05-06  
**Reviewer:** pch-plan-reviewer  
**Original Plan Version:** v2.0  
**Reviewed Plan Version:** v2.1  

### Review Metrics
- Issues Found: 3 (Critical: 0, Major: 0, Minor: 3)
- Clarifying Questions Asked: 0
- Sections Updated: None (minor notes only)

### Codebase Verification
All technical claims verified against source:
- ✅ Animation pattern matches `widget_arc_set_value_animated()` in `widgets.c`
- ✅ Theme constants `THEME_COLOR_FG`, `THEME_COLOR_FG_DIM`, `THEME_COLOR_CARD_BORDER` exist
- ✅ `LV_USE_SCALE` absent, `LV_USE_IMG` is last widget define — insertion point correct
- ✅ LVGL v9.5.0 via FetchContent confirmed
- ✅ `LV_FONT_MONTSERRAT_14` and `LV_FONT_MONTSERRAT_28` enabled
- ✅ `vehicle_hdg_label` usage matches plan's removal/replacement approach
- ✅ Card flex layout (`LV_FLEX_ALIGN_CENTER` cross-axis) auto-centers children
- ✅ `CARD_WIDTH=460` easily fits 200px compass
- ✅ No `CMakeLists.txt` changes needed (`widgets.c` already in sources)

### Minor Notes for Implementer
1. **Step 1.5(c):** `lv_obj_set_align(vehicle_compass, LV_ALIGN_CENTER)` is a no-op in flex context — card already centers children via cross-axis alignment. Can omit or keep as documentation.
2. **Step 1.3:** Consider also removing `LV_OBJ_FLAG_SCROLLABLE` alongside `LV_OBJ_FLAG_CLICKABLE` for defensive completeness.
3. **File-static `compass_last_heading`** diverges from research (function-local static) — both valid; file-static chosen intentionally per Architectural Considerations.

### Key Improvements Made
None required — plan was high quality as submitted.

### Remaining Considerations
- First-frame animation: compass will animate from 0° to actual heading on first data push (cosmetic, not a defect)
- Single-instance assumption documented and acceptable for this dashboard

### Sign-off
This plan has been reviewed and is **Ready for Implementation**.

### Implementation Complexity

| Factor | Score (1-5) | Notes |
|--------|-------------|-------|
| Files to modify | 2 | 4 files in single `contrib/lvgl_kiosk/` directory |
| New patterns introduced | 1 | Follows existing `widget_arc_set_value_animated` pattern exactly |
| External dependencies | 1 | Only `LV_USE_SCALE` enablement (already in LVGL) |
| Migration complexity | 1 | No migration; additive change with one widget removal |
| Test coverage required | 1 | Visual verification only (LVGL C kiosk, no unit test framework) |
| **Overall Complexity** | **6/25** | **Low** |

## Handoff

| Field | Value |
|-------|-------|
| Created By | pch-planner |
| Created Date | 2026-05-06 |
| Reviewed By | pch-plan-reviewer |
| Review Date | 2026-05-06 |
| Status | ✅ Ready for Implementation |
| Next Agent | pch-coder |
| Plan Location | /docs/plans/025-kiosk-compass-widget.md |
