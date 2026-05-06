/**
 * widgets.h — Reusable LVGL widget helpers for the mower kiosk dashboard
 *
 * Provides factory functions for arc gauges, animated bars, LEDs,
 * line charts, and scrolling labels with consistent styling.
 */
#ifndef WIDGETS_H
#define WIDGETS_H

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Create a 270° arc gauge widget.
 *
 * @param parent      Parent container
 * @param size        Arc diameter in pixels
 * @param start_angle Starting angle (degrees, 0=top)
 * @param end_angle   Ending angle (degrees)
 * @return            The created arc object
 */
lv_obj_t *widget_create_arc_gauge(lv_obj_t *parent, int size,
                                  int start_angle, int end_angle);

/**
 * Set arc gauge value with smooth animation.
 *
 * @param arc   Arc object from widget_create_arc_gauge()
 * @param value Current value (0..max)
 * @param max   Maximum value
 */
void widget_arc_set_value_animated(lv_obj_t *arc, int value, int max);

/**
 * Create a styled progress bar.
 *
 * @param parent  Parent container
 * @param width   Bar width in pixels
 * @param height  Bar height in pixels
 * @return        The created bar object
 */
lv_obj_t *widget_create_bar(lv_obj_t *parent, int width, int height);

/**
 * Set bar value with smooth animation.
 *
 * @param bar    Bar object from widget_create_bar()
 * @param value  Value 0..100
 */
void widget_bar_set_value_animated(lv_obj_t *bar, int value);

/**
 * Create an LED indicator.
 *
 * @param parent  Parent container
 * @param size    LED diameter in pixels
 * @return        The created LED object
 */
lv_obj_t *widget_create_led(lv_obj_t *parent, int size);

/**
 * Set LED color based on service status string.
 * "active"/"running" → green, "failed"/"dead" → red, others → amber.
 *
 * @param led     LED object from widget_create_led()
 * @param status  Status string (e.g. "active", "failed", "inactive")
 */
void widget_led_set_status(lv_obj_t *led, const char *status);

/**
 * Create a line chart with configured series.
 *
 * @param parent       Parent container
 * @param width        Chart width in pixels
 * @param height       Chart height in pixels
 * @param point_count  Number of points in the scrolling buffer
 * @return             The created chart object
 */
lv_obj_t *widget_create_chart(lv_obj_t *parent, int width, int height,
                              int point_count);

/**
 * Add a data point to the chart series (scrolls left).
 *
 * @param chart   Chart object from widget_create_chart()
 * @param series  Chart series handle
 * @param value   New data value
 */
void widget_chart_add_point(lv_obj_t *chart, lv_chart_series_t *series,
                            int value);

/**
 * Create a scrolling label (long text mode = SCROLL_CIRCULAR).
 *
 * @param parent  Parent container
 * @return        The created label object
 */
lv_obj_t *widget_create_scroll_label(lv_obj_t *parent);

#ifdef __cplusplus
}
#endif

#endif /* WIDGETS_H */
