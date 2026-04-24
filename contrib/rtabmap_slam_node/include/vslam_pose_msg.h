/**
 * @file vslam_pose_msg.h
 * @brief IPC wire format for VSLAM pose messages over Unix domain socket.
 *
 * Packed binary struct sent from rtabmap_slam_node to the Python bridge.
 * Total size: 118 bytes.
 * Python struct.unpack format: "<Q6f21fBB"
 *
 * Covariance layout: upper triangle of the 6×6 pose covariance matrix,
 * row-major order (21 floats):
 *   [0..5]   = row 0: cov(x,x), cov(x,y), cov(x,z), cov(x,roll), cov(x,pitch), cov(x,yaw)
 *   [6..9]   = row 1: cov(y,y), cov(y,z), cov(y,roll), cov(y,pitch), cov(y,yaw)
 *   [10..12] = row 2: cov(z,z), cov(z,roll), cov(z,pitch), cov(z,yaw)
 *   [13..14] = row 3: cov(roll,roll), cov(roll,pitch), cov(roll,yaw)
 *   [15..16] = row 4: cov(pitch,pitch), cov(pitch,yaw)
 *   [17]     = row 5: cov(yaw,yaw)
 *   ... wait, that's only 18.  Actually 21 = 6+5+4+3+2+1 entries.
 *   Indices:
 *     row 0 (6): [0..5]
 *     row 1 (5): [6..10]
 *     row 2 (4): [11..14]
 *     row 3 (3): [15..17]
 *     row 4 (2): [18..19]
 *     row 5 (1): [20]
 */

#ifndef VSLAM_POSE_MSG_H
#define VSLAM_POSE_MSG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Packed pose message: 118 bytes total.
 *
 * Layout:
 *   uint64_t  timestamp_us   (8  bytes) — microseconds since epoch
 *   float     x              (4  bytes) — position east  (metres, NED)
 *   float     y              (4  bytes) — position north (metres, NED)
 *   float     z              (4  bytes) — position down  (metres, NED)
 *   float     roll           (4  bytes) — radians
 *   float     pitch          (4  bytes) — radians
 *   float     yaw            (4  bytes) — radians
 *   float     covariance[21] (84 bytes) — upper triangle of 6×6 covariance
 *   uint8_t   confidence     (1  byte)  — 0–100 quality metric
 *   uint8_t   reset_counter  (1  byte)  — increments on each odometry reset
 *                             -----------
 *                             118 bytes
 */
struct __attribute__((packed)) vslam_pose_msg {
    uint64_t timestamp_us;
    float x;
    float y;
    float z;
    float roll;
    float pitch;
    float yaw;
    float covariance[21];
    uint8_t confidence;
    uint8_t reset_counter;
};

/* Compile-time size check. */
_Static_assert(sizeof(struct vslam_pose_msg) == 118,
               "vslam_pose_msg must be exactly 118 bytes");

#ifdef __cplusplus
}
#endif

#endif /* VSLAM_POSE_MSG_H */
