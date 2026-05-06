/**
 * widgets.c — Reusable LVGL widget helpers for the mower kiosk dashboard
 */
#include "widgets.h"
#include "theme.h"

#include <string.h>

/* Animation durations */
#define ARC_ANIM_DURATION_MS  500
#define BAR_ANIM_DURATION_MS  300

/* ─── Arc Gauge ─────────────────────────────────────────────────────── */

lv_obj_t *widget_create_arc_gauge(lv_obj_t *parent, int size,
                                  int start_angle, int end_angle)
{
    lv_obj_t *arc = lv_arc_create(parent);
    lv_obj_set_size(arc, size, size);
    lv_arc_set_rotation(arc, 135);
    lv_arc_set_bg_angles(arc, (uint32_t)start_angle, (uint32_t)end_angle);
    lv_arc_set_value(arc, 0);
    lv_arc_set_range(arc, 0, 100);

    /* Remove knob */
    lv_obj_set_style_pad_all(arc, 0, LV_PART_KNOB);
    lv_obj_set_style_bg_opa(arc, LV_OPA_TRANSP, LV_PART_KNOB);

    /* Background arc styling */
    lv_obj_set_style_arc_color(arc, THEME_COLOR_CARD_BORDER, LV_PART_MAIN);
    lv_obj_set_style_arc_width(arc, 12, LV_PART_MAIN);

    /* Indicator arc styling */
    lv_obj_set_style_arc_color(arc, THEME_COLOR_OK, LV_PART_INDICATOR);
    lv_obj_set_style_arc_width(arc, 12, LV_PART_INDICATOR);

    /* Non-interactive */
    lv_obj_remove_flag(arc, LV_OBJ_FLAG_CLICKABLE);

    return arc;
}

static void arc_anim_cb(void *obj, int32_t value)
{
    lv_arc_set_value((lv_obj_t *)obj, (int16_t)value);
}

void widget_arc_set_value_animated(lv_obj_t *arc, int value, int max)
{
    lv_arc_set_range(arc, 0, (int16_t)max);
    int16_t current = lv_arc_get_value(arc);

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, arc);
    lv_anim_set_values(&a, current, (int32_t)value);
    lv_anim_set_duration(&a, ARC_ANIM_DURATION_MS);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    lv_anim_set_exec_cb(&a, arc_anim_cb);
    lv_anim_start(&a);
}

/* ─── Bar ───────────────────────────────────────────────────────────── */

lv_obj_t *widget_create_bar(lv_obj_t *parent, int width, int height)
{
    lv_obj_t *bar = lv_bar_create(parent);
    lv_obj_set_size(bar, width, height);
    lv_bar_set_range(bar, 0, 100);
    lv_bar_set_value(bar, 0, LV_ANIM_OFF);

    /* Background */
    lv_obj_set_style_bg_color(bar, THEME_COLOR_CARD_BORDER, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(bar, 4, LV_PART_MAIN);

    /* Indicator */
    lv_obj_set_style_bg_color(bar, THEME_COLOR_OK, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, 4, LV_PART_INDICATOR);

    return bar;
}

static void bar_anim_cb(void *obj, int32_t value)
{
    lv_bar_set_value((lv_obj_t *)obj, (int32_t)value, LV_ANIM_OFF);
}

void widget_bar_set_value_animated(lv_obj_t *bar, int value)
{
    int32_t current = lv_bar_get_value(bar);

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, bar);
    lv_anim_set_values(&a, current, (int32_t)value);
    lv_anim_set_duration(&a, BAR_ANIM_DURATION_MS);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    lv_anim_set_exec_cb(&a, bar_anim_cb);
    lv_anim_start(&a);
}

/* ─── LED ───────────────────────────────────────────────────────────── */

lv_obj_t *widget_create_led(lv_obj_t *parent, int size)
{
    lv_obj_t *led = lv_led_create(parent);
    lv_obj_set_size(led, size, size);
    lv_led_set_color(led, THEME_COLOR_STALE);
    lv_led_set_brightness(led, 80);
    return led;
}

void widget_led_set_status(lv_obj_t *led, const char *status)
{
    if (status == NULL || status[0] == '\0') {
        lv_led_set_color(led, THEME_COLOR_STALE);
        lv_led_set_brightness(led, 80);
        return;
    }

    if (strcmp(status, "active") == 0 || strcmp(status, "running") == 0) {
        lv_led_set_color(led, THEME_COLOR_OK);
        lv_led_set_brightness(led, 255);
    } else if (strcmp(status, "failed") == 0 || strcmp(status, "dead") == 0) {
        lv_led_set_color(led, THEME_COLOR_ERROR);
        lv_led_set_brightness(led, 255);
    } else {
        lv_led_set_color(led, THEME_COLOR_WARN);
        lv_led_set_brightness(led, 180);
    }
}

/* ─── Chart ─────────────────────────────────────────────────────────── */

lv_obj_t *widget_create_chart(lv_obj_t *parent, int width, int height,
                              int point_count)
{
    lv_obj_t *chart = lv_chart_create(parent);
    lv_obj_set_size(chart, width, height);
    lv_chart_set_type(chart, LV_CHART_TYPE_LINE);
    lv_chart_set_point_count(chart, (uint16_t)point_count);
    lv_chart_set_range(chart, LV_CHART_AXIS_PRIMARY_Y, 0, 60);
    lv_chart_set_div_line_count(chart, 3, 0);
    lv_chart_set_update_mode(chart, LV_CHART_UPDATE_MODE_SHIFT);

    /* Style */
    lv_obj_set_style_bg_color(chart, THEME_COLOR_CARD_BG, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(chart, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_border_width(chart, 0, LV_PART_MAIN);
    lv_obj_set_style_line_color(chart, THEME_COLOR_CARD_BORDER, LV_PART_MAIN);

    /* Series line style */
    lv_obj_set_style_size(chart, 0, 0, LV_PART_INDICATOR); /* hide data points */

    return chart;
}

void widget_chart_add_point(lv_obj_t *chart, lv_chart_series_t *series,
                            int value)
{
    lv_chart_set_next_value2(chart, series, LV_CHART_POINT_NONE, value);
}

/* ─── Scrolling Label ───────────────────────────────────────────────── */

lv_obj_t *widget_create_scroll_label(lv_obj_t *parent)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_long_mode(label, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_width(label, lv_pct(100));
    lv_obj_set_style_text_color(label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_18, 0);
    return label;
}
