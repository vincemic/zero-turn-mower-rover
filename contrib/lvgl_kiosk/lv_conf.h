/**
 * lv_conf.h — LVGL configuration for Mower Kiosk Renderer
 * Wayland SHM + 32-bit color, NEON acceleration, full widget set.
 * No EGL/GPU rendering (pixman Weston on Tegra234 card0).
 */
#ifndef LV_CONF_H
#define LV_CONF_H

/* Enable LVGL configuration */
#define LV_CONF_SKIP 0

/* Color depth: 32-bit ARGB */
#define LV_COLOR_DEPTH 32

/* Wayland display driver (SHM, no EGL) */
#define LV_USE_WAYLAND          1
#define LV_USE_OPENGLES         0
#define LV_USE_G2D              0
#define LV_WAYLAND_WL_SHELL     0

/* Refresh at ~30 FPS */
#define LV_DEF_REFR_PERIOD      33

/* Software draw — NEON acceleration on aarch64 */
#define LV_DRAW_SW_ASM          LV_DRAW_SW_ASM_NEON

/* Widgets needed for dashboard */
#define LV_USE_ARC              1
#define LV_USE_BAR              1
#define LV_USE_CHART            1
#define LV_USE_LABEL            1
#define LV_USE_LED              1
#define LV_USE_SPINNER          1
#define LV_USE_TABLE            1
#define LV_USE_BTN              1
#define LV_USE_IMG              1

/* Animation support */
#define LV_USE_ANIM             1

/* Observer pattern (needed internally) */
#define LV_USE_OBSERVER         1

/* Fonts — multiple sizes for dashboard hierarchy */
#define LV_FONT_MONTSERRAT_14   1
#define LV_FONT_MONTSERRAT_18   1
#define LV_FONT_MONTSERRAT_22   1
#define LV_FONT_MONTSERRAT_28   1
#define LV_FONT_MONTSERRAT_36   1

/* Default font */
#define LV_FONT_DEFAULT         &lv_font_montserrat_18

/* Memory: use stdlib malloc (Jetson has plenty of RAM) */
#define LV_USE_STDLIB_MALLOC    LV_STDLIB_BUILTIN
#define LV_MEM_SIZE             (256 * 1024)

/* Logging */
#define LV_USE_LOG              1
#define LV_LOG_LEVEL            LV_LOG_LEVEL_WARN

#endif /* LV_CONF_H */
