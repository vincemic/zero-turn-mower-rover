/**
 * theme.c — High-contrast outdoor color scheme for the mower kiosk
 *
 * Sets up LVGL styles for maximum readability on a sunlit outdoor display.
 * Black background, white text, high-saturation status colors.
 */
#include "theme.h"

/** Global style objects */
static lv_style_t style_screen;
static lv_style_t style_card;
static lv_style_t style_label_title;
static lv_style_t style_label_value;
static lv_style_t style_label_dim;

void create_theme(void)
{
    /* Screen background — pure black */
    lv_style_init(&style_screen);
    lv_style_set_bg_color(&style_screen, THEME_COLOR_BG);
    lv_style_set_bg_opa(&style_screen, LV_OPA_COVER);
    lv_style_set_text_color(&style_screen, THEME_COLOR_FG);
    lv_style_set_text_font(&style_screen, &lv_font_montserrat_18);

    /* Apply screen style to active screen */
    lv_obj_add_style(lv_screen_active(), &style_screen, 0);

    /* Card panel style — dark grey with subtle border */
    lv_style_init(&style_card);
    lv_style_set_bg_color(&style_card, THEME_COLOR_CARD_BG);
    lv_style_set_bg_opa(&style_card, LV_OPA_COVER);
    lv_style_set_border_color(&style_card, THEME_COLOR_CARD_BORDER);
    lv_style_set_border_width(&style_card, 1);
    lv_style_set_radius(&style_card, 8);
    lv_style_set_pad_all(&style_card, 12);

    /* Title labels — larger, white */
    lv_style_init(&style_label_title);
    lv_style_set_text_color(&style_label_title, THEME_COLOR_FG);
    lv_style_set_text_font(&style_label_title, &lv_font_montserrat_22);

    /* Value labels — large, white */
    lv_style_init(&style_label_value);
    lv_style_set_text_color(&style_label_value, THEME_COLOR_FG);
    lv_style_set_text_font(&style_label_value, &lv_font_montserrat_28);

    /* Dimmed labels — secondary information */
    lv_style_init(&style_label_dim);
    lv_style_set_text_color(&style_label_dim, THEME_COLOR_FG_DIM);
    lv_style_set_text_font(&style_label_dim, &lv_font_montserrat_14);
}
