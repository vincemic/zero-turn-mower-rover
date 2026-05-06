/**
 * json_parser.c — Parse kiosk display JSON frames
 *
 * Uses vendored cJSON to extract SharedState fields from the IPC payload.
 */
#include "json_parser.h"
#include "cjson/cJSON.h"

#include <string.h>
#include <time.h>

/** Safe string copy into a fixed-size buffer */
static void safe_strcpy(char *dst, size_t dst_size, const char *src)
{
    if (src == NULL) {
        dst[0] = '\0';
        return;
    }
    size_t len = strlen(src);
    if (len >= dst_size) {
        len = dst_size - 1;
    }
    memcpy(dst, src, len);
    dst[len] = '\0';
}

/** Get current monotonic time in milliseconds */
static uint64_t get_monotonic_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

/** Helper: get a string from a cJSON object field */
static const char *get_str(const cJSON *obj, const char *key)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (cJSON_IsString(item)) {
        return cJSON_GetStringValue(item);
    }
    return NULL;
}

/** Helper: get a double from a cJSON object field */
static double get_num(const cJSON *obj, const char *key, double fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (cJSON_IsNumber(item)) {
        return cJSON_GetNumberValue(item);
    }
    return fallback;
}

/** Helper: get an int from a cJSON object field */
static int get_int(const cJSON *obj, const char *key, int fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (cJSON_IsNumber(item)) {
        return item->valueint;
    }
    return fallback;
}

/** Helper: get a bool from a cJSON object field */
static bool get_bool(const cJSON *obj, const char *key, bool fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (cJSON_IsBool(item)) {
        return cJSON_IsTrue(item);
    }
    return fallback;
}

/** Parse the "mav" sub-object */
static void parse_mav(const cJSON *mav, kiosk_data_t *out)
{
    if (mav == NULL || !cJSON_IsObject(mav)) {
        return;
    }

    out->mav_armed = get_bool(mav, "armed", false);
    const char *mode = get_str(mav, "mode");
    safe_strcpy(out->mav_mode, sizeof(out->mav_mode), mode);
    out->mav_system_status = get_int(mav, "system_status", 0);
    out->mav_groundspeed_ms = get_num(mav, "groundspeed_ms", 0.0);
    out->mav_heading_deg = get_int(mav, "heading_deg", 0);
    out->mav_throttle_pct = get_int(mav, "throttle_pct", 0);
    out->mav_gps1_fix = get_int(mav, "gps1_fix", 0);
    out->mav_gps1_sats = get_int(mav, "gps1_sats", 0);
    out->mav_gps1_hdop = get_num(mav, "gps1_hdop", 99.99);
    out->mav_gps2_fix = get_int(mav, "gps2_fix", 0);
    out->mav_gps2_sats = get_int(mav, "gps2_sats", 0);
    out->mav_gps2_hdop = get_num(mav, "gps2_hdop", 99.99);
    out->mav_rtk1_baseline_mm = get_int(mav, "rtk1_baseline_mm", 0);
    out->mav_rtk1_iar = get_int(mav, "rtk1_iar", 0);
    out->mav_rtk2_baseline_mm = get_int(mav, "rtk2_baseline_mm", 0);
    out->mav_rtk2_iar = get_int(mav, "rtk2_iar", 0);
    const char *statustext = get_str(mav, "last_statustext");
    safe_strcpy(out->mav_last_statustext, sizeof(out->mav_last_statustext), statustext);
    out->mav_last_heartbeat_epoch = get_num(mav, "last_heartbeat_epoch", 0.0);
    out->mav_last_gps_epoch = get_num(mav, "last_gps_epoch", 0.0);
}

/** Parse the "vslam" sub-object */
static void parse_vslam(const cJSON *vslam, kiosk_data_t *out)
{
    if (vslam == NULL || !cJSON_IsObject(vslam)) {
        return;
    }

    out->vslam_rate_hz = get_num(vslam, "rate_hz", 0.0);
    out->vslam_confidence = get_int(vslam, "confidence", 0);
    out->vslam_age_ms = get_int(vslam, "age_ms", 0);
    out->vslam_covariance_norm = get_num(vslam, "covariance_norm", 0.0);
}

/** Parse the "health" sub-object */
static void parse_health(const cJSON *health, kiosk_data_t *out)
{
    if (health == NULL || !cJSON_IsObject(health)) {
        return;
    }

    out->health_cpu_temp_c = get_num(health, "cpu_temp_c", 0.0);
    out->health_gpu_temp_c = get_num(health, "gpu_temp_c", 0.0);
    const char *power = get_str(health, "power_mode");
    safe_strcpy(out->health_power_mode, sizeof(out->health_power_mode), power);
    const char *fan = get_str(health, "fan_status");
    safe_strcpy(out->health_fan_status, sizeof(out->health_fan_status), fan);
}

/** Parse the "storage" sub-object */
static void parse_storage(const cJSON *storage, kiosk_data_t *out)
{
    if (storage == NULL || !cJSON_IsObject(storage)) {
        return;
    }

    out->storage_nvme_pct = get_num(storage, "nvme_pct", 0.0);
    const char *free_gb = get_str(storage, "nvme_free_gb");
    safe_strcpy(out->storage_nvme_free_gb, sizeof(out->storage_nvme_free_gb), free_gb);
    out->storage_root_pct = get_num(storage, "root_pct", 0.0);
}

/** Parse the "services" sub-object */
static void parse_services(const cJSON *services, kiosk_data_t *out)
{
    if (services == NULL || !cJSON_IsObject(services)) {
        return;
    }

    const char *slam = get_str(services, "slam_node");
    safe_strcpy(out->svc_slam_node, sizeof(out->svc_slam_node), slam);
    const char *bridge = get_str(services, "vslam_bridge");
    safe_strcpy(out->svc_vslam_bridge, sizeof(out->svc_vslam_bridge), bridge);
    const char *health = get_str(services, "health_monitor");
    safe_strcpy(out->svc_health_monitor, sizeof(out->svc_health_monitor), health);
    const char *mav = get_str(services, "mavproxy");
    safe_strcpy(out->svc_mavproxy, sizeof(out->svc_mavproxy), mav);
}

bool parse_kiosk_json(const char *json_buf, size_t len, kiosk_data_t *out)
{
    if (json_buf == NULL || len == 0 || out == NULL) {
        return false;
    }

    memset(out, 0, sizeof(*out));

    /* cJSON requires null-terminated input; use ParseWithLength for safety */
    cJSON *root = cJSON_ParseWithLength(json_buf, len);
    if (root == NULL) {
        return false;
    }

    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return false;
    }

    /* Parse top-level sections */
    parse_mav(cJSON_GetObjectItemCaseSensitive(root, "mav"), out);

    /* Wi-Fi (top-level fields) */
    const char *wifi_iface = get_str(root, "wifi_interface");
    safe_strcpy(out->wifi_interface, sizeof(out->wifi_interface), wifi_iface);
    out->wifi_signal_dbm = get_num(root, "wifi_signal_dbm", 0.0);
    out->wifi_link_quality = get_num(root, "wifi_link_quality", 0.0);

    /* Sub-objects */
    parse_vslam(cJSON_GetObjectItemCaseSensitive(root, "vslam"), out);
    parse_health(cJSON_GetObjectItemCaseSensitive(root, "health"), out);
    parse_storage(cJSON_GetObjectItemCaseSensitive(root, "storage"), out);
    parse_services(cJSON_GetObjectItemCaseSensitive(root, "services"), out);

    /* Metadata */
    const char *last_update = get_str(root, "last_update");
    safe_strcpy(out->last_update, sizeof(out->last_update), last_update);

    cJSON_Delete(root);

    out->valid = true;
    out->parse_time_ms = get_monotonic_ms();

    return true;
}
