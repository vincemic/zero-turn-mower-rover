/**
 * dashboard.c — 8-card operational dashboard for the mower kiosk
 *
 * Layout: 4×2 grid of cards at 1920×1080, with a top status bar.
 * Each card shows real-time data from the kiosk IPC socket.
 */
#include "dashboard.h"
#include "widgets.h"
#include "theme.h"

#include <stdio.h>
#include <string.h>

/* Layout constants */
#define STATUS_BAR_HEIGHT 40
#define CARD_WIDTH        460
#define CARD_PAD          10
#define CARD_COLS         4
#define CARD_ROWS         2
#define CHART_POINTS      60

/* ─── Static widget references ──────────────────────────────────────── */

/* Status bar */
static lv_obj_t *status_bar       = NULL;
static lv_obj_t *status_label     = NULL;
static lv_obj_t *stale_label      = NULL;

/* Connecting overlay */
static lv_obj_t *connect_overlay  = NULL;
static lv_obj_t *connect_spinner  = NULL;
static lv_obj_t *connect_label    = NULL;
static bool      first_frame_received = false;

/* Card 0: VSLAM */
static lv_obj_t *vslam_chart      = NULL;
static lv_chart_series_t *vslam_series = NULL;
static lv_obj_t *vslam_led        = NULL;
static lv_obj_t *vslam_fps_label  = NULL;
static lv_obj_t *vslam_conf_label = NULL;

/* Card 1: Vehicle */
static lv_obj_t *vehicle_led      = NULL;
static lv_obj_t *vehicle_mode_label  = NULL;
static lv_obj_t *vehicle_speed_label = NULL;
static lv_obj_t *vehicle_hdg_label   = NULL;

/* Card 2: GPS/RTK */
static lv_obj_t *gps_arc          = NULL;
static lv_obj_t *gps_sats_label   = NULL;
static lv_obj_t *gps_hdop_label   = NULL;
static lv_obj_t *gps_baseline_label = NULL;

/* Card 3: System Health */
static lv_obj_t *cpu_bar          = NULL;
static lv_obj_t *gpu_bar          = NULL;
static lv_obj_t *cpu_temp_label   = NULL;
static lv_obj_t *gpu_temp_label   = NULL;
static lv_obj_t *power_label      = NULL;
static lv_obj_t *fan_label        = NULL;

/* Card 4: Storage */
static lv_obj_t *nvme_bar         = NULL;
static lv_obj_t *nvme_pct_label   = NULL;
static lv_obj_t *nvme_free_label  = NULL;
static lv_obj_t *root_pct_label   = NULL;

/* Card 5: Wi-Fi */
static lv_obj_t *wifi_arc         = NULL;
static lv_obj_t *wifi_iface_label = NULL;
static lv_obj_t *wifi_qual_label  = NULL;

/* Card 6: Services */
static lv_obj_t *svc_led[4]       = {NULL};
static lv_obj_t *svc_name_label[4]= {NULL};

/* Card 7: Alerts */
static lv_obj_t *alert_label      = NULL;
static lv_obj_t *alert_card       = NULL;

/* ─── Helper: create a card container ───────────────────────────────── */

static lv_obj_t *create_card(lv_obj_t *parent, const char *title)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_set_size(card, CARD_WIDTH, LV_SIZE_CONTENT);
    lv_obj_set_flex_grow(card, 1);
    lv_obj_set_style_min_height(card, 480, 0);
    lv_obj_set_style_max_width(card, CARD_WIDTH, 0);
    lv_obj_set_style_bg_color(card, THEME_COLOR_CARD_BG, 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(card, THEME_COLOR_CARD_BORDER, 0);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_set_style_radius(card, 8, 0);
    lv_obj_set_style_pad_all(card, CARD_PAD, 0);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(card, 6, 0);

    /* Title label */
    lv_obj_t *lbl = lv_label_create(card);
    lv_label_set_text(lbl, title);
    lv_obj_set_style_text_color(lbl, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(lbl, &lv_font_montserrat_14, 0);

    return card;
}

/* ─── Helper: color for temperature value ───────────────────────────── */

static lv_color_t temp_color(double temp_c)
{
    if (temp_c > 80.0) return THEME_COLOR_ERROR;
    if (temp_c >= 60.0) return THEME_COLOR_WARN;
    return THEME_COLOR_OK;
}

/* ─── Helper: color for GPS fix quality ─────────────────────────────── */

static lv_color_t gps_fix_color(int fix)
{
    if (fix >= 5) return THEME_COLOR_OK;
    if (fix == 4) return THEME_COLOR_WARN;
    return THEME_COLOR_ERROR;
}

/* ─── Helper: color for WiFi signal ─────────────────────────────────── */

static lv_color_t wifi_color(double dbm)
{
    if (dbm > -50.0) return THEME_COLOR_OK;
    if (dbm >= -70.0) return THEME_COLOR_WARN;
    return THEME_COLOR_ERROR;
}

/* ─── Helper: color for storage percent ─────────────────────────────── */

static lv_color_t storage_color(double pct)
{
    if (pct > 90.0) return THEME_COLOR_ERROR;
    if (pct >= 75.0) return THEME_COLOR_WARN;
    return THEME_COLOR_OK;
}

/* ─── Status Bar ────────────────────────────────────────────────────── */

static void create_status_bar(lv_obj_t *parent)
{
    status_bar = lv_obj_create(parent);
    lv_obj_set_size(status_bar, lv_pct(100), STATUS_BAR_HEIGHT);
    lv_obj_set_style_bg_color(status_bar, THEME_COLOR_CARD_BG, 0);
    lv_obj_set_style_bg_opa(status_bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(status_bar, 0, 0);
    lv_obj_set_style_radius(status_bar, 0, 0);
    lv_obj_set_style_pad_hor(status_bar, 10, 0);
    lv_obj_set_flex_flow(status_bar, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(status_bar, LV_FLEX_ALIGN_SPACE_BETWEEN,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    status_label = lv_label_create(status_bar);
    lv_label_set_text(status_label, "MOWER KIOSK");
    lv_obj_set_style_text_color(status_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_16, 0);

    stale_label = lv_label_create(status_bar);
    lv_label_set_text(stale_label, "");
    lv_obj_set_style_text_color(stale_label, THEME_COLOR_ERROR, 0);
    lv_obj_set_style_text_font(stale_label, &lv_font_montserrat_16, 0);
    lv_obj_add_flag(stale_label, LV_OBJ_FLAG_HIDDEN);
}

/* ─── Card 0: VSLAM ────────────────────────────────────────────────── */

static void create_card_vslam(lv_obj_t *parent)
{
    lv_obj_t *card = create_card(parent, "VSLAM");

    /* Line chart for FPS history */
    vslam_chart = widget_create_chart(card, 420, 200, CHART_POINTS);
    lv_chart_set_range(vslam_chart, LV_CHART_AXIS_PRIMARY_Y, 0, 60);
    vslam_series = lv_chart_add_series(vslam_chart, THEME_COLOR_OK,
                                       LV_CHART_AXIS_PRIMARY_Y);

    /* LED: VSLAM health indicator */
    lv_obj_t *row = lv_obj_create(card);
    lv_obj_set_size(row, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(row, 0, 0);
    lv_obj_set_style_pad_all(row, 0, 0);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(row, 8, 0);

    vslam_led = widget_create_led(row, 16);

    vslam_fps_label = lv_label_create(row);
    lv_label_set_text(vslam_fps_label, "-- Hz");
    lv_obj_set_style_text_color(vslam_fps_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(vslam_fps_label, &lv_font_montserrat_18, 0);

    vslam_conf_label = lv_label_create(card);
    lv_label_set_text(vslam_conf_label, "Confidence: --");
    lv_obj_set_style_text_color(vslam_conf_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(vslam_conf_label, &lv_font_montserrat_14, 0);
}

/* ─── Card 1: Vehicle ──────────────────────────────────────────────── */

static void create_card_vehicle(lv_obj_t *parent)
{
    lv_obj_t *card = create_card(parent, "VEHICLE");

    /* Armed LED */
    lv_obj_t *row = lv_obj_create(card);
    lv_obj_set_size(row, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(row, 0, 0);
    lv_obj_set_style_pad_all(row, 0, 0);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(row, 8, 0);

    vehicle_led = widget_create_led(row, 20);

    vehicle_mode_label = lv_label_create(row);
    lv_label_set_text(vehicle_mode_label, "MODE: --");
    lv_obj_set_style_text_color(vehicle_mode_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(vehicle_mode_label, &lv_font_montserrat_24, 0);

    vehicle_speed_label = lv_label_create(card);
    lv_label_set_text(vehicle_speed_label, "Speed: -- m/s");
    lv_obj_set_style_text_color(vehicle_speed_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(vehicle_speed_label, &lv_font_montserrat_18, 0);

    vehicle_hdg_label = lv_label_create(card);
    lv_label_set_text(vehicle_hdg_label, "Heading: --°");
    lv_obj_set_style_text_color(vehicle_hdg_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(vehicle_hdg_label, &lv_font_montserrat_18, 0);
}

/* ─── Card 2: GPS/RTK ──────────────────────────────────────────────── */

static void create_card_gps(lv_obj_t *parent)
{
    lv_obj_t *card = create_card(parent, "GPS / RTK");

    /* 270° arc gauge for fix quality (0-6 scale) */
    gps_arc = widget_create_arc_gauge(card, 180, 0, 270);
    lv_obj_set_align(gps_arc, LV_ALIGN_CENTER);

    gps_sats_label = lv_label_create(card);
    lv_label_set_text(gps_sats_label, "Sats: --");
    lv_obj_set_style_text_color(gps_sats_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(gps_sats_label, &lv_font_montserrat_18, 0);

    gps_hdop_label = lv_label_create(card);
    lv_label_set_text(gps_hdop_label, "HDOP: --");
    lv_obj_set_style_text_color(gps_hdop_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(gps_hdop_label, &lv_font_montserrat_14, 0);

    gps_baseline_label = lv_label_create(card);
    lv_label_set_text(gps_baseline_label, "Baseline: --");
    lv_obj_set_style_text_color(gps_baseline_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(gps_baseline_label, &lv_font_montserrat_14, 0);
}

/* ─── Card 3: System Health ─────────────────────────────────────────── */

static void create_card_health(lv_obj_t *parent)
{
    lv_obj_t *card = create_card(parent, "SYSTEM HEALTH");

    /* CPU temperature bar */
    lv_obj_t *cpu_row = lv_obj_create(card);
    lv_obj_set_size(cpu_row, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(cpu_row, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(cpu_row, 0, 0);
    lv_obj_set_style_pad_all(cpu_row, 0, 0);
    lv_obj_set_flex_flow(cpu_row, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(cpu_row, 4, 0);

    cpu_temp_label = lv_label_create(cpu_row);
    lv_label_set_text(cpu_temp_label, "CPU: --°C");
    lv_obj_set_style_text_color(cpu_temp_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(cpu_temp_label, &lv_font_montserrat_16, 0);

    cpu_bar = widget_create_bar(cpu_row, 420, 20);

    /* GPU temperature bar */
    lv_obj_t *gpu_row = lv_obj_create(card);
    lv_obj_set_size(gpu_row, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(gpu_row, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(gpu_row, 0, 0);
    lv_obj_set_style_pad_all(gpu_row, 0, 0);
    lv_obj_set_flex_flow(gpu_row, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(gpu_row, 4, 0);

    gpu_temp_label = lv_label_create(gpu_row);
    lv_label_set_text(gpu_temp_label, "GPU: --°C");
    lv_obj_set_style_text_color(gpu_temp_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(gpu_temp_label, &lv_font_montserrat_16, 0);

    gpu_bar = widget_create_bar(gpu_row, 420, 20);

    /* Power mode and fan */
    power_label = lv_label_create(card);
    lv_label_set_text(power_label, "Power: --");
    lv_obj_set_style_text_color(power_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(power_label, &lv_font_montserrat_14, 0);

    fan_label = lv_label_create(card);
    lv_label_set_text(fan_label, "Fan: --");
    lv_obj_set_style_text_color(fan_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(fan_label, &lv_font_montserrat_14, 0);
}

/* ─── Card 4: Storage ──────────────────────────────────────────────── */

static void create_card_storage(lv_obj_t *parent)
{
    lv_obj_t *card = create_card(parent, "STORAGE");

    nvme_pct_label = lv_label_create(card);
    lv_label_set_text(nvme_pct_label, "NVMe: --%");
    lv_obj_set_style_text_color(nvme_pct_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(nvme_pct_label, &lv_font_montserrat_18, 0);

    nvme_bar = widget_create_bar(card, 420, 24);

    nvme_free_label = lv_label_create(card);
    lv_label_set_text(nvme_free_label, "Free: --");
    lv_obj_set_style_text_color(nvme_free_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(nvme_free_label, &lv_font_montserrat_14, 0);

    root_pct_label = lv_label_create(card);
    lv_label_set_text(root_pct_label, "Root: --%");
    lv_obj_set_style_text_color(root_pct_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(root_pct_label, &lv_font_montserrat_14, 0);
}

/* ─── Card 5: Wi-Fi ────────────────────────────────────────────────── */

static void create_card_wifi(lv_obj_t *parent)
{
    lv_obj_t *card = create_card(parent, "WI-FI");

    wifi_arc = widget_create_arc_gauge(card, 160, 0, 270);
    lv_obj_set_align(wifi_arc, LV_ALIGN_CENTER);

    wifi_iface_label = lv_label_create(card);
    lv_label_set_text(wifi_iface_label, "Interface: --");
    lv_obj_set_style_text_color(wifi_iface_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(wifi_iface_label, &lv_font_montserrat_16, 0);

    wifi_qual_label = lv_label_create(card);
    lv_label_set_text(wifi_qual_label, "Signal: --");
    lv_obj_set_style_text_color(wifi_qual_label, THEME_COLOR_FG_DIM, 0);
    lv_obj_set_style_text_font(wifi_qual_label, &lv_font_montserrat_14, 0);
}

/* ─── Card 6: Services ─────────────────────────────────────────────── */

static void create_card_services(lv_obj_t *parent)
{
    lv_obj_t *card = create_card(parent, "SERVICES");

    static const char *svc_names[4] = {
        "slam-node", "vslam-bridge", "health-mon", "mavproxy"
    };

    for (int i = 0; i < 4; i++) {
        lv_obj_t *row = lv_obj_create(card);
        lv_obj_set_size(row, lv_pct(100), LV_SIZE_CONTENT);
        lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(row, 0, 0);
        lv_obj_set_style_pad_all(row, 2, 0);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                              LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_column(row, 8, 0);

        svc_led[i] = widget_create_led(row, 14);

        svc_name_label[i] = lv_label_create(row);
        lv_label_set_text(svc_name_label[i], svc_names[i]);
        lv_obj_set_style_text_color(svc_name_label[i], THEME_COLOR_FG, 0);
        lv_obj_set_style_text_font(svc_name_label[i], &lv_font_montserrat_16, 0);
    }
}

/* ─── Card 7: Alerts ───────────────────────────────────────────────── */

static void create_card_alerts(lv_obj_t *parent)
{
    alert_card = create_card(parent, "ALERTS");

    alert_label = widget_create_scroll_label(alert_card);
    lv_label_set_text(alert_label, "No alerts");
    lv_obj_set_style_text_font(alert_label, &lv_font_montserrat_18, 0);
}

/* ─── Connecting Overlay ────────────────────────────────────────────── */

static void create_connecting_overlay(void)
{
    connect_overlay = lv_obj_create(lv_screen_active());
    lv_obj_set_size(connect_overlay, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(connect_overlay, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(connect_overlay, LV_OPA_80, 0);
    lv_obj_set_style_border_width(connect_overlay, 0, 0);
    lv_obj_set_style_radius(connect_overlay, 0, 0);
    lv_obj_set_flex_flow(connect_overlay, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(connect_overlay, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(connect_overlay, 20, 0);

    connect_spinner = lv_spinner_create(connect_overlay);
    lv_obj_set_size(connect_spinner, 80, 80);
    lv_spinner_set_anim_params(connect_spinner, 1000, 270);

    connect_label = lv_label_create(connect_overlay);
    lv_label_set_text(connect_label, "CONNECTING...");
    lv_obj_set_style_text_color(connect_label, THEME_COLOR_FG, 0);
    lv_obj_set_style_text_font(connect_label, &lv_font_montserrat_24, 0);
}

/* ─── Public: create_dashboard ──────────────────────────────────────── */

void create_dashboard(void)
{
    lv_obj_t *screen = lv_screen_active();

    /* Black background */
    lv_obj_set_style_bg_color(screen, THEME_COLOR_BG, 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);

    /* Root flex column: status bar + grid */
    lv_obj_set_flex_flow(screen, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(screen, 0, 0);
    lv_obj_set_style_pad_row(screen, 0, 0);

    /* Status bar */
    create_status_bar(screen);

    /* Card grid container */
    lv_obj_t *grid = lv_obj_create(screen);
    lv_obj_set_size(grid, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_flex_grow(grid, 1);
    lv_obj_set_style_bg_opa(grid, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(grid, 0, 0);
    lv_obj_set_style_pad_all(grid, CARD_PAD, 0);
    lv_obj_set_style_pad_gap(grid, CARD_PAD, 0);
    lv_obj_set_flex_flow(grid, LV_FLEX_FLOW_ROW_WRAP);
    lv_obj_set_flex_align(grid, LV_FLEX_ALIGN_SPACE_EVENLY,
                          LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    /* Row 1: VSLAM, Vehicle, GPS, Health */
    create_card_vslam(grid);
    create_card_vehicle(grid);
    create_card_gps(grid);
    create_card_health(grid);

    /* Row 2: Storage, WiFi, Services, Alerts */
    create_card_storage(grid);
    create_card_wifi(grid);
    create_card_services(grid);
    create_card_alerts(grid);

    /* Connecting overlay (on top of everything, initially visible) */
    create_connecting_overlay();
    first_frame_received = false;
}

/* ─── Public: update_dashboard ──────────────────────────────────────── */

void update_dashboard(const kiosk_data_t *data)
{
    if (data == NULL) return;

    /* Hide connecting overlay on first valid frame */
    if (!first_frame_received) {
        first_frame_received = true;
        dashboard_set_connecting(false);
    }

    /* Card 0: VSLAM */
    widget_chart_add_point(vslam_chart, vslam_series, (int)data->vslam_rate_hz);
    lv_label_set_text_fmt(vslam_fps_label, "%.1f Hz", data->vslam_rate_hz);
    lv_label_set_text_fmt(vslam_conf_label, "Confidence: %d%%",
                          data->vslam_confidence);

    if (data->vslam_rate_hz > 5.0 && data->vslam_confidence > 50) {
        lv_led_set_color(vslam_led, THEME_COLOR_OK);
        lv_led_set_brightness(vslam_led, 255);
    } else if (data->vslam_rate_hz > 0.0) {
        lv_led_set_color(vslam_led, THEME_COLOR_WARN);
        lv_led_set_brightness(vslam_led, 180);
    } else {
        lv_led_set_color(vslam_led, THEME_COLOR_ERROR);
        lv_led_set_brightness(vslam_led, 255);
    }

    /* Card 1: Vehicle */
    if (data->mav_armed) {
        lv_led_set_color(vehicle_led, THEME_COLOR_ERROR);
        lv_led_set_brightness(vehicle_led, 255);
    } else {
        lv_led_set_color(vehicle_led, THEME_COLOR_OK);
        lv_led_set_brightness(vehicle_led, 200);
    }
    lv_label_set_text_fmt(vehicle_mode_label, "%s", data->mav_mode);
    lv_label_set_text_fmt(vehicle_speed_label, "Speed: %.1f m/s",
                          data->mav_groundspeed_ms);
    lv_label_set_text_fmt(vehicle_hdg_label, "Heading: %d°",
                          data->mav_heading_deg);

    /* Card 2: GPS/RTK */
    widget_arc_set_value_animated(gps_arc, data->mav_gps1_fix, 6);
    lv_obj_set_style_arc_color(gps_arc, gps_fix_color(data->mav_gps1_fix),
                               LV_PART_INDICATOR);
    lv_label_set_text_fmt(gps_sats_label, "Sats: %d", data->mav_gps1_sats);
    lv_label_set_text_fmt(gps_hdop_label, "HDOP: %.2f", data->mav_gps1_hdop);
    lv_label_set_text_fmt(gps_baseline_label, "Baseline: %d mm",
                          data->mav_rtk1_baseline_mm);

    /* Card 3: System Health */
    int cpu_pct = (int)data->health_cpu_temp_c;  /* 0-100 scale */
    int gpu_pct = (int)data->health_gpu_temp_c;
    widget_bar_set_value_animated(cpu_bar, cpu_pct);
    widget_bar_set_value_animated(gpu_bar, gpu_pct);
    lv_obj_set_style_bg_color(cpu_bar, temp_color(data->health_cpu_temp_c),
                              LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(gpu_bar, temp_color(data->health_gpu_temp_c),
                              LV_PART_INDICATOR);
    lv_label_set_text_fmt(cpu_temp_label, "CPU: %.0f°C",
                          data->health_cpu_temp_c);
    lv_label_set_text_fmt(gpu_temp_label, "GPU: %.0f°C",
                          data->health_gpu_temp_c);
    lv_label_set_text_fmt(power_label, "Power: %s", data->health_power_mode);
    lv_label_set_text_fmt(fan_label, "Fan: %s", data->health_fan_status);

    /* Card 4: Storage */
    int nvme_val = (int)data->storage_nvme_pct;
    widget_bar_set_value_animated(nvme_bar, nvme_val);
    lv_obj_set_style_bg_color(nvme_bar, storage_color(data->storage_nvme_pct),
                              LV_PART_INDICATOR);
    lv_label_set_text_fmt(nvme_pct_label, "NVMe: %d%%", nvme_val);
    lv_label_set_text_fmt(nvme_free_label, "Free: %s",
                          data->storage_nvme_free_gb);
    lv_label_set_text_fmt(root_pct_label, "Root: %.0f%%",
                          data->storage_root_pct);

    /* Card 5: Wi-Fi */
    /* Map dBm (-100..0) to 0..100 for arc display */
    int wifi_val = (int)(100.0 + data->wifi_signal_dbm);
    if (wifi_val < 0) wifi_val = 0;
    if (wifi_val > 100) wifi_val = 100;
    widget_arc_set_value_animated(wifi_arc, wifi_val, 100);
    lv_obj_set_style_arc_color(wifi_arc, wifi_color(data->wifi_signal_dbm),
                               LV_PART_INDICATOR);
    lv_label_set_text_fmt(wifi_iface_label, "%s", data->wifi_interface);
    lv_label_set_text_fmt(wifi_qual_label, "Signal: %.0f dBm",
                          data->wifi_signal_dbm);

    /* Card 6: Services */
    widget_led_set_status(svc_led[0], data->svc_slam_node);
    widget_led_set_status(svc_led[1], data->svc_vslam_bridge);
    widget_led_set_status(svc_led[2], data->svc_health_monitor);
    widget_led_set_status(svc_led[3], data->svc_mavproxy);

    /* Card 7: Alerts */
    if (data->mav_last_statustext[0] != '\0') {
        lv_label_set_text(alert_label, data->mav_last_statustext);

        /* Color background based on severity keywords */
        if (strstr(data->mav_last_statustext, "FAIL") ||
            strstr(data->mav_last_statustext, "ERR") ||
            strstr(data->mav_last_statustext, "CRIT")) {
            lv_obj_set_style_bg_color(alert_card, lv_color_hex(0x330000), 0);
        } else if (strstr(data->mav_last_statustext, "WARN")) {
            lv_obj_set_style_bg_color(alert_card, lv_color_hex(0x332200), 0);
        } else {
            lv_obj_set_style_bg_color(alert_card, THEME_COLOR_CARD_BG, 0);
        }
    }
}

/* ─── Public: dashboard_set_stale ───────────────────────────────────── */

void dashboard_set_stale(bool stale)
{
    if (stale_label == NULL) return;

    if (stale) {
        lv_label_set_text(stale_label, "DATA STALE");
        lv_obj_remove_flag(stale_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_bg_color(status_bar, THEME_COLOR_ERROR, 0);
    } else {
        lv_label_set_text(stale_label, "");
        lv_obj_add_flag(stale_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_bg_color(status_bar, THEME_COLOR_CARD_BG, 0);
    }
}

/* ─── Public: dashboard_set_connecting ──────────────────────────────── */

void dashboard_set_connecting(bool connecting)
{
    if (connect_overlay == NULL) return;

    if (connecting) {
        lv_obj_remove_flag(connect_overlay, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(connect_overlay, LV_OBJ_FLAG_HIDDEN);
    }
}
