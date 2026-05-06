/**
 * main.c — Mower Kiosk Renderer entry point
 *
 * LVGL-based fullscreen Wayland kiosk for the Zero-Turn Mower Rover.
 * Connects to the Python kiosk data server via Unix socket, receives
 * JSON state frames, and renders a real-time operational dashboard.
 *
 * Signal handling: SIGTERM/SIGINT trigger graceful shutdown.
 * sd_notify: Reports READY=1 on start, WATCHDOG=1 periodically, STOPPING=1 on exit.
 */
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include <systemd/sd-daemon.h>

#include "lvgl/lvgl.h"
#include "socket_client.h"
#include "json_parser.h"
#include "theme.h"
#include "dashboard.h"

/* Default socket path */
#define KIOSK_SOCKET_PATH "/run/mower/kiosk-display.sock"

/* Window dimensions */
#define WINDOW_WIDTH  1920
#define WINDOW_HEIGHT 1080

/* Timer intervals (ms) */
#define SOCKET_POLL_INTERVAL_MS  100   /* 10 Hz socket check */
#define STALENESS_CHECK_MS       1000  /* 1 Hz data age check */
#define WATCHDOG_INTERVAL_MS     15000 /* sd_notify WATCHDOG=1 */

/* Staleness detection threshold (ms) */
#define STALENESS_THRESHOLD_MS   5000

/* Shutdown flag */
static volatile sig_atomic_t g_shutdown = 0;

/* Timestamp of last successful data frame (monotonic ms) */
static uint64_t last_data_time_ms = 0;

static void signal_handler(int sig)
{
    (void)sig;
    g_shutdown = 1;
}

static void setup_signal_handlers(void)
{
    struct sigaction sa;
    sa.sa_handler = signal_handler;
    sa.sa_flags = 0;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
}

/**
 * Socket poll timer callback — called at 10 Hz.
 * Receives and parses JSON frames from the Python data server.
 */
static void socket_poll_cb(lv_timer_t *timer)
{
    (void)timer;

    const kiosk_data_t *data = socket_client_poll();
    if (data != NULL) {
        last_data_time_ms = lv_tick_get();
        update_dashboard(data);
    }
}

/**
 * Staleness check timer callback — called at 1 Hz.
 * Detects stale data (no updates for >5s) and updates UI accordingly.
 */
static void staleness_cb(lv_timer_t *timer)
{
    (void)timer;

    if (!socket_client_connected()) {
        dashboard_set_connecting(true);
        return;
    }

    if (last_data_time_ms == 0) {
        /* No data received yet */
        return;
    }

    uint64_t now = lv_tick_get();
    uint64_t elapsed = now - last_data_time_ms;

    dashboard_set_stale(elapsed > STALENESS_THRESHOLD_MS);
}

/**
 * Watchdog timer callback — sends sd_notify WATCHDOG=1.
 */
static void watchdog_cb(lv_timer_t *timer)
{
    (void)timer;
    sd_notify(0, "WATCHDOG=1");
}

int main(void)
{
    setup_signal_handlers();

    lv_init();

    lv_display_t *disp = lv_wayland_window_create(WINDOW_WIDTH, WINDOW_HEIGHT,
                                                   "Mower Kiosk", NULL);
    if (!disp) {
        fprintf(stderr, "ERROR: Failed to create Wayland window\n");
        lv_deinit();
        return 1;
    }
    lv_wayland_window_set_fullscreen(disp, true);

    /* Initialize theme (high-contrast outdoor colors) */
    create_theme();

    /* Build full dashboard widget tree */
    create_dashboard();

    /* Initialize socket client */
    socket_client_init(KIOSK_SOCKET_PATH);

    /* Create timers */
    lv_timer_create(socket_poll_cb, SOCKET_POLL_INTERVAL_MS, NULL);
    lv_timer_create(staleness_cb, STALENESS_CHECK_MS, NULL);
    lv_timer_create(watchdog_cb, WATCHDOG_INTERVAL_MS, NULL);

    /* Notify systemd that we're ready */
    sd_notify(0, "READY=1");

    fprintf(stderr, "kiosk: renderer started, waiting for data on %s\n",
            KIOSK_SOCKET_PATH);

    /* Main event loop */
    while (lv_wayland_window_is_open(disp) && !g_shutdown) {
        uint32_t ms = lv_timer_handler();
        lv_delay_ms(ms);
    }

    /* Graceful shutdown */
    sd_notify(0, "STOPPING=1");
    socket_client_close();
    lv_wayland_window_delete(disp);
    lv_deinit();

    fprintf(stderr, "kiosk: clean exit\n");
    return 0;
}
