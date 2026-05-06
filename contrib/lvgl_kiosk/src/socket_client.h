/**
 * socket_client.h — Non-blocking Unix domain socket client for kiosk IPC
 *
 * Connects to the Python kiosk data server and receives length-prefixed
 * JSON frames. Designed to be polled from an LVGL timer callback.
 */
#ifndef SOCKET_CLIENT_H
#define SOCKET_CLIENT_H

#include <stdbool.h>
#include "json_parser.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the socket client.
 * Does not block — connection attempt happens on first poll.
 *
 * @param path  Unix domain socket path (e.g. "/run/mower/kiosk-display.sock")
 */
void socket_client_init(const char *path);

/**
 * Close the socket connection and free resources.
 */
void socket_client_close(void);

/**
 * Poll the socket for new data (non-blocking).
 *
 * Call this from an LVGL timer at ~10 Hz. If a complete JSON frame has been
 * received and parsed, returns a pointer to the internal kiosk_data_t.
 * The returned pointer is valid until the next call to socket_client_poll().
 *
 * @return  Pointer to parsed data if a new frame is available, NULL otherwise.
 */
const kiosk_data_t *socket_client_poll(void);

/**
 * Check if the socket is currently connected.
 *
 * @return  true if connected, false if disconnected or connecting.
 */
bool socket_client_connected(void);

#ifdef __cplusplus
}
#endif

#endif /* SOCKET_CLIENT_H */
