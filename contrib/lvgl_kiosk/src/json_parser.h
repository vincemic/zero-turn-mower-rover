/**
 * json_parser.h — Parse kiosk display JSON frames from IPC socket
 *
 * Extracts all SharedState fields from the JSON payload into a flat C struct.
 */
#ifndef JSON_PARSER_H
#define JSON_PARSER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Maximum string buffer length for parsed text fields */
#define KIOSK_STR_MAX 128

/** Parsed kiosk data — mirrors Python SharedState.snapshot() output */
typedef struct {
    /* mav section */
    bool     mav_armed;
    char     mav_mode[KIOSK_STR_MAX];
    int      mav_system_status;
    double   mav_groundspeed_ms;
    int      mav_heading_deg;
    int      mav_throttle_pct;
    int      mav_gps1_fix;
    int      mav_gps1_sats;
    double   mav_gps1_hdop;
    int      mav_gps2_fix;
    int      mav_gps2_sats;
    double   mav_gps2_hdop;
    int      mav_rtk1_baseline_mm;
    int      mav_rtk1_iar;
    int      mav_rtk2_baseline_mm;
    int      mav_rtk2_iar;
    char     mav_last_statustext[KIOSK_STR_MAX];
    double   mav_last_heartbeat_epoch;
    double   mav_last_gps_epoch;

    /* wifi */
    char     wifi_interface[KIOSK_STR_MAX];
    double   wifi_signal_dbm;
    double   wifi_link_quality;

    /* vslam */
    double   vslam_rate_hz;
    int      vslam_confidence;
    int      vslam_age_ms;
    double   vslam_covariance_norm;

    /* health */
    double   health_cpu_temp_c;
    double   health_gpu_temp_c;
    char     health_power_mode[KIOSK_STR_MAX];
    char     health_fan_status[KIOSK_STR_MAX];

    /* storage */
    double   storage_nvme_pct;
    char     storage_nvme_free_gb[KIOSK_STR_MAX];
    double   storage_root_pct;

    /* services */
    char     svc_slam_node[KIOSK_STR_MAX];
    char     svc_vslam_bridge[KIOSK_STR_MAX];
    char     svc_health_monitor[KIOSK_STR_MAX];
    char     svc_mavproxy[KIOSK_STR_MAX];

    /* metadata */
    char     last_update[KIOSK_STR_MAX];

    /* parse metadata */
    bool     valid;          /* true if parsing succeeded */
    uint64_t parse_time_ms;  /* monotonic time when this frame was parsed */
} kiosk_data_t;

/**
 * Parse a JSON buffer into a kiosk_data_t struct.
 *
 * @param json_buf  Pointer to JSON payload (not necessarily null-terminated)
 * @param len       Length of JSON payload in bytes
 * @param out       Output struct (zeroed on entry, filled on success)
 * @return          true on successful parse, false on error
 */
bool parse_kiosk_json(const char *json_buf, size_t len, kiosk_data_t *out);

#ifdef __cplusplus
}
#endif

#endif /* JSON_PARSER_H */
