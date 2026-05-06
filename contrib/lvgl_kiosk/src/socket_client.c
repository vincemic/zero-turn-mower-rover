/**
 * socket_client.c — Non-blocking Unix domain socket client
 *
 * Implements length-prefixed frame protocol:
 *   [4 bytes LE uint32 length][UTF-8 JSON payload]
 *
 * Reconnects automatically on disconnect with exponential backoff.
 */
#include "socket_client.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

/** Maximum receive buffer size */
#define RECV_BUF_SIZE 8192

/** Reconnect interval bounds (milliseconds) */
#define RECONNECT_MIN_MS 500
#define RECONNECT_MAX_MS 10000

/** Socket client state */
static struct {
    int fd;
    char path[108];  /* sun_path max */
    bool connected;

    /* Receive buffer */
    uint8_t buf[RECV_BUF_SIZE];
    size_t buf_len;

    /* Parsed frame */
    kiosk_data_t frame;

    /* Reconnect state */
    uint64_t last_connect_attempt_ms;
    uint32_t reconnect_interval_ms;
} s_client = {
    .fd = -1,
    .connected = false,
    .buf_len = 0,
    .last_connect_attempt_ms = 0,
    .reconnect_interval_ms = RECONNECT_MIN_MS,
};

/** Get monotonic time in milliseconds */
static uint64_t mono_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

/** Set socket to non-blocking mode */
static bool set_nonblocking(int fd)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags == -1) {
        return false;
    }
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK) != -1;
}

/** Attempt to connect to the Unix socket */
static bool try_connect(void)
{
    uint64_t now = mono_ms();

    /* Respect reconnect backoff */
    if (now - s_client.last_connect_attempt_ms < s_client.reconnect_interval_ms) {
        return false;
    }
    s_client.last_connect_attempt_ms = now;

    /* Close any existing fd */
    if (s_client.fd >= 0) {
        close(s_client.fd);
        s_client.fd = -1;
    }

    s_client.fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (s_client.fd < 0) {
        fprintf(stderr, "kiosk: socket() failed: %s\n", strerror(errno));
        return false;
    }

    if (!set_nonblocking(s_client.fd)) {
        fprintf(stderr, "kiosk: fcntl() failed: %s\n", strerror(errno));
        close(s_client.fd);
        s_client.fd = -1;
        return false;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, s_client.path, sizeof(addr.sun_path) - 1);

    int ret = connect(s_client.fd, (struct sockaddr *)&addr, sizeof(addr));
    if (ret == 0) {
        /* Connected immediately */
        s_client.connected = true;
        s_client.reconnect_interval_ms = RECONNECT_MIN_MS;
        s_client.buf_len = 0;
        fprintf(stderr, "kiosk: connected to %s\n", s_client.path);
        return true;
    }

    if (errno == EINPROGRESS) {
        /* Connection in progress — treat as not yet connected, will retry */
        close(s_client.fd);
        s_client.fd = -1;
    } else {
        /* Connection refused or path not found */
        close(s_client.fd);
        s_client.fd = -1;
    }

    /* Exponential backoff */
    s_client.reconnect_interval_ms *= 2;
    if (s_client.reconnect_interval_ms > RECONNECT_MAX_MS) {
        s_client.reconnect_interval_ms = RECONNECT_MAX_MS;
    }

    return false;
}

/** Handle disconnect */
static void handle_disconnect(void)
{
    if (s_client.fd >= 0) {
        close(s_client.fd);
        s_client.fd = -1;
    }
    s_client.connected = false;
    s_client.buf_len = 0;
    fprintf(stderr, "kiosk: disconnected from %s\n", s_client.path);
}

void socket_client_init(const char *path)
{
    memset(&s_client, 0, sizeof(s_client));
    s_client.fd = -1;
    s_client.connected = false;
    s_client.reconnect_interval_ms = RECONNECT_MIN_MS;

    if (path != NULL) {
        strncpy(s_client.path, path, sizeof(s_client.path) - 1);
    }
}

void socket_client_close(void)
{
    if (s_client.fd >= 0) {
        close(s_client.fd);
        s_client.fd = -1;
    }
    s_client.connected = false;
    s_client.buf_len = 0;
}

const kiosk_data_t *socket_client_poll(void)
{
    /* If not connected, try to connect */
    if (!s_client.connected) {
        try_connect();
        return NULL;
    }

    /* Non-blocking recv */
    ssize_t n = recv(s_client.fd, s_client.buf + s_client.buf_len,
                     sizeof(s_client.buf) - s_client.buf_len, MSG_DONTWAIT);

    if (n > 0) {
        s_client.buf_len += (size_t)n;
    } else if (n == 0) {
        /* Peer closed connection */
        handle_disconnect();
        return NULL;
    } else {
        /* n < 0 */
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            /* Real error */
            handle_disconnect();
            return NULL;
        }
        /* EAGAIN/EWOULDBLOCK: no data available, that's fine */
    }

    /* Try to extract a complete frame: [4-byte LE length][payload] */
    while (s_client.buf_len >= 4) {
        uint32_t msg_len;
        memcpy(&msg_len, s_client.buf, 4);

        /* Sanity check: reject absurdly large messages */
        if (msg_len > RECV_BUF_SIZE - 4) {
            fprintf(stderr, "kiosk: message too large (%u bytes), dropping\n", msg_len);
            handle_disconnect();
            return NULL;
        }

        /* Not enough data yet for the full message */
        if (s_client.buf_len < 4 + msg_len) {
            break;
        }

        /* Parse the JSON payload */
        bool ok = parse_kiosk_json((const char *)(s_client.buf + 4), msg_len, &s_client.frame);

        /* Consume the message from the buffer */
        size_t consumed = 4 + msg_len;
        memmove(s_client.buf, s_client.buf + consumed, s_client.buf_len - consumed);
        s_client.buf_len -= consumed;

        if (ok) {
            return &s_client.frame;
        }
    }

    return NULL;
}

bool socket_client_connected(void)
{
    return s_client.connected;
}
