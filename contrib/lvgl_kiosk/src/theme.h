/**
 * theme.h — High-contrast outdoor color scheme for the mower kiosk
 *
 * All colors are designed for visibility on a sunlit outdoor display.
 */
#ifndef THEME_H
#define THEME_H

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Background and foreground */
#define THEME_COLOR_BG          lv_color_hex(0x000000)  /* Pure black background */
#define THEME_COLOR_FG          lv_color_hex(0xFFFFFF)  /* White text */
#define THEME_COLOR_FG_DIM      lv_color_hex(0xAAAAAA)  /* Dimmed/secondary text */

/* Status colors */
#define THEME_COLOR_OK          lv_color_hex(0x00FF00)  /* Green — healthy/active */
#define THEME_COLOR_WARN        lv_color_hex(0xFFAA00)  /* Amber — warning */
#define THEME_COLOR_ERROR       lv_color_hex(0xFF0000)  /* Red — error/critical */
#define THEME_COLOR_STALE       lv_color_hex(0x888888)  /* Grey — stale/unknown */

/* Card/panel colors */
#define THEME_COLOR_CARD_BG     lv_color_hex(0x1A1A1A)  /* Dark grey card background */
#define THEME_COLOR_CARD_BORDER lv_color_hex(0x333333)  /* Subtle card border */

/* GPS/RTK specific */
#define THEME_COLOR_RTK_FIXED   lv_color_hex(0x00FF00)  /* Green — RTK fixed */
#define THEME_COLOR_RTK_FLOAT   lv_color_hex(0xFFAA00)  /* Amber — RTK float */
#define THEME_COLOR_GPS_3D      lv_color_hex(0x00AAFF)  /* Blue — 3D fix */
#define THEME_COLOR_GPS_NONE    lv_color_hex(0xFF0000)  /* Red — no fix */

/**
 * Initialize the high-contrast kiosk theme.
 * Must be called after lv_init() and before creating widgets.
 */
void create_theme(void);

#ifdef __cplusplus
}
#endif

#endif /* THEME_H */
