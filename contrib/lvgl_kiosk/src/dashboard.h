/**
 * dashboard.h — 8-card operational dashboard layout
 *
 * Creates and updates the full kiosk widget tree: VSLAM, Vehicle, GPS/RTK,
 * System Health, Storage, Wi-Fi, Services, and Alerts cards.
 */
#ifndef DASHBOARD_H
#define DASHBOARD_H

#include "json_parser.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Build the full 8-card dashboard widget tree.
 * Call once after create_theme() and before the main loop.
 */
void create_dashboard(void);

/**
 * Update all dashboard widgets from a parsed data frame.
 *
 * @param data  Pointer to parsed kiosk data (valid for this call only)
 */
void update_dashboard(const kiosk_data_t *data);

/**
 * Show or hide the "DATA STALE" status bar.
 *
 * @param stale  true to show stale indicator, false to hide
 */
void dashboard_set_stale(bool stale);

/**
 * Show or hide the "CONNECTING..." overlay with spinner.
 *
 * @param connecting  true to show connecting overlay, false to hide
 */
void dashboard_set_connecting(bool connecting);

#ifdef __cplusplus
}
#endif

#endif /* DASHBOARD_H */
