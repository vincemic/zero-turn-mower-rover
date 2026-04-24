/**
 * @file rtabmap_slam_node.cpp
 * @brief Standalone RTAB-Map SLAM process for the mower rover.
 *
 * Reads stereo depth + IMU from an OAK-D Pro via depthai-core,
 * feeds frames to RTAB-Map (OdometryF2M + Rtabmap), and publishes
 * SE3 poses over a Unix domain socket in the vslam_pose_msg wire
 * format.
 *
 * Designed to run as a systemd Type=notify service on Jetson AGX Orin.
 *
 * Usage:
 *   rtabmap_slam_node --config /etc/mower/vslam.yaml
 */

#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

/* Unix socket headers. */
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

/* systemd notification. */
#include <systemd/sd-daemon.h>

/* YAML-cpp for config. */
#include <yaml-cpp/yaml.h>

/* depthai-core. */
#include <depthai/depthai.hpp>

/* RTAB-Map core. */
#include <rtabmap/core/CameraModel.h>
#include <rtabmap/core/Memory.h>
#include <rtabmap/core/Odometry.h>
#include <rtabmap/core/OdometryF2M.h>
#include <rtabmap/core/Parameters.h>
#include <rtabmap/core/Rtabmap.h>
#include <rtabmap/core/SensorData.h>
#include <rtabmap/core/Transform.h>
#include <rtabmap/utilite/ULogger.h>
#include <rtabmap/utilite/UStl.h>

/* OpenCV (used by RTAB-Map SensorData). */
#include <opencv2/core.hpp>

/* IPC wire format. */
#include "vslam_pose_msg.h"

/* --------------------------------------------------------------------------
 * Signal handling
 * -------------------------------------------------------------------------- */

static std::atomic<bool> g_shutdown{false};

static void signal_handler(int sig) {
    (void)sig;
    g_shutdown.store(true);
}

/* --------------------------------------------------------------------------
 * Configuration
 * -------------------------------------------------------------------------- */

struct SlamConfig {
    /* Socket / IPC. */
    std::string socket_path = "/run/mower/vslam-pose.sock";

    /* Camera. */
    std::string stereo_resolution = "400p";
    int stereo_fps = 30;
    int imu_rate_hz = 200;

    /* RTAB-Map. */
    std::string odometry_strategy = "f2m";
    int pose_output_rate_hz = 20;
    int memory_threshold_mb = 6000;
    bool loop_closure = true;
    std::string database_path = "/var/lib/mower/rtabmap.db";
};

static SlamConfig load_config(const std::string &path) {
    SlamConfig cfg;
    if (path.empty()) {
        std::cerr << "[config] No config path; using defaults" << std::endl;
        return cfg;
    }

    std::ifstream ifs(path);
    if (!ifs.is_open()) {
        std::cerr << "[config] Cannot open " << path
                  << "; using defaults" << std::endl;
        return cfg;
    }

    try {
        YAML::Node root = YAML::LoadFile(path);
        YAML::Node vslam = root["vslam"];
        if (!vslam) {
            std::cerr << "[config] No 'vslam' key; using defaults" << std::endl;
            return cfg;
        }

        if (vslam["socket_path"])
            cfg.socket_path = vslam["socket_path"].as<std::string>();
        if (vslam["stereo_resolution"])
            cfg.stereo_resolution = vslam["stereo_resolution"].as<std::string>();
        if (vslam["stereo_fps"])
            cfg.stereo_fps = vslam["stereo_fps"].as<int>();
        if (vslam["imu_rate_hz"])
            cfg.imu_rate_hz = vslam["imu_rate_hz"].as<int>();
        if (vslam["odometry_strategy"])
            cfg.odometry_strategy = vslam["odometry_strategy"].as<std::string>();
        if (vslam["pose_output_rate_hz"])
            cfg.pose_output_rate_hz = vslam["pose_output_rate_hz"].as<int>();
        if (vslam["memory_threshold_mb"])
            cfg.memory_threshold_mb = vslam["memory_threshold_mb"].as<int>();
        if (vslam["loop_closure"])
            cfg.loop_closure = vslam["loop_closure"].as<bool>();
        if (vslam["database_path"])
            cfg.database_path = vslam["database_path"].as<std::string>();

        std::cerr << "[config] Loaded from " << path << std::endl;
    } catch (const YAML::Exception &e) {
        std::cerr << "[config] YAML parse error: " << e.what()
                  << "; using defaults" << std::endl;
    }

    return cfg;
}

/* --------------------------------------------------------------------------
 * Stereo resolution helper
 * -------------------------------------------------------------------------- */

static dai::MonoCameraProperties::SensorResolution
resolve_mono_resolution(const std::string &res) {
    if (res == "480p")
        return dai::MonoCameraProperties::SensorResolution::THE_480_P;
    if (res == "720p")
        return dai::MonoCameraProperties::SensorResolution::THE_720_P;
    if (res == "800p")
        return dai::MonoCameraProperties::SensorResolution::THE_800_P;
    /* Default: 400p. */
    return dai::MonoCameraProperties::SensorResolution::THE_400_P;
}

/* --------------------------------------------------------------------------
 * DepthAI pipeline setup
 * -------------------------------------------------------------------------- */

struct DaiPipeline {
    std::shared_ptr<dai::Device> device;
    std::shared_ptr<dai::DataOutputQueue> stereo_queue;
    std::shared_ptr<dai::DataOutputQueue> left_queue;
    std::shared_ptr<dai::DataOutputQueue> right_queue;
    std::shared_ptr<dai::DataOutputQueue> imu_queue;
};

static DaiPipeline create_depthai_pipeline(const SlamConfig &cfg) {
    dai::Pipeline pipeline;

    /* Mono cameras. */
    auto mono_left = pipeline.create<dai::node::MonoCamera>();
    auto mono_right = pipeline.create<dai::node::MonoCamera>();
    auto resolution = resolve_mono_resolution(cfg.stereo_resolution);
    mono_left->setResolution(resolution);
    mono_left->setBoardSocket(dai::CameraBoardSocket::CAM_B);
    mono_left->setFps(static_cast<float>(cfg.stereo_fps));
    mono_right->setResolution(resolution);
    mono_right->setBoardSocket(dai::CameraBoardSocket::CAM_C);
    mono_right->setFps(static_cast<float>(cfg.stereo_fps));

    /* Stereo depth. */
    auto stereo = pipeline.create<dai::node::StereoDepth>();
    stereo->setDefaultProfilePreset(
        dai::node::StereoDepth::PresetMode::HIGH_DENSITY);
    stereo->setLeftRightCheck(true);
    stereo->setSubpixel(true);
    stereo->setExtendedDisparity(false);
    mono_left->out.link(stereo->left);
    mono_right->out.link(stereo->right);

    /* Depth output. */
    auto xout_depth = pipeline.create<dai::node::XLinkOut>();
    xout_depth->setStreamName("depth");
    stereo->depth.link(xout_depth->input);

    /* Left rectified output (for RTAB-Map). */
    auto xout_left = pipeline.create<dai::node::XLinkOut>();
    xout_left->setStreamName("rectified_left");
    stereo->rectifiedLeft.link(xout_left->input);

    /* Right rectified output (for RTAB-Map). */
    auto xout_right = pipeline.create<dai::node::XLinkOut>();
    xout_right->setStreamName("rectified_right");
    stereo->rectifiedRight.link(xout_right->input);

    /* IMU. */
    auto imu = pipeline.create<dai::node::IMU>();
    imu->enableIMUSensor(
        dai::IMUSensor::ACCELEROMETER_RAW, cfg.imu_rate_hz);
    imu->enableIMUSensor(
        dai::IMUSensor::GYROSCOPE_RAW, cfg.imu_rate_hz);
    imu->setBatchReportThreshold(1);
    imu->setMaxBatchReports(10);
    auto xout_imu = pipeline.create<dai::node::XLinkOut>();
    xout_imu->setStreamName("imu");
    imu->out.link(xout_imu->input);

    /* Start device. */
    std::cerr << "[depthai] Starting device..." << std::endl;
    auto device = std::make_shared<dai::Device>(pipeline);
    std::cerr << "[depthai] Device started: "
              << device->getDeviceId() << std::endl;

    auto calib = device->readCalibration();
    auto intrinsics = calib.getCameraIntrinsics(
        dai::CameraBoardSocket::CAM_B);
    std::cerr << "[depthai] Left camera fx=" << intrinsics[0][0]
              << " fy=" << intrinsics[1][1]
              << " cx=" << intrinsics[0][2]
              << " cy=" << intrinsics[1][2] << std::endl;

    DaiPipeline result;
    result.device = device;
    result.stereo_queue = device->getOutputQueue("depth", 4, false);
    result.left_queue = device->getOutputQueue("rectified_left", 4, false);
    result.right_queue = device->getOutputQueue("rectified_right", 4, false);
    result.imu_queue = device->getOutputQueue("imu", 50, false);
    return result;
}

/* --------------------------------------------------------------------------
 * RTAB-Map setup
 * -------------------------------------------------------------------------- */

struct SlamEngine {
    rtabmap::OdometryF2M *odometry = nullptr;
    rtabmap::Rtabmap *rtabmap_engine = nullptr;
    uint8_t reset_counter = 0;
};

static SlamEngine create_slam_engine(const SlamConfig &cfg) {
    ULogger::setType(ULogger::kTypeConsole);
    ULogger::setLevel(ULogger::kWarning);

    rtabmap::ParametersMap params;

    /* Odometry parameters. */
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kOdomResetCountdown(), "0"));
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kVisMinInliers(), "10"));
    params.insert(rtabmap::ParametersPair(
        rtabmap::Parameters::kOdomF2MMaxSize(), "3000"));

    /* Memory management. */
    char mem_str[32];
    snprintf(mem_str, sizeof(mem_str), "%d", cfg.memory_threshold_mb);

    /* Loop closure. */
    if (!cfg.loop_closure) {
        params.insert(rtabmap::ParametersPair(
            rtabmap::Parameters::kRGBDEnabled(), "false"));
    }

    SlamEngine engine;

    /* Create odometry (F2M = Frame-to-Map). */
    engine.odometry = new rtabmap::OdometryF2M(params);

    /* Create RTAB-Map. */
    engine.rtabmap_engine = new rtabmap::Rtabmap();
    engine.rtabmap_engine->init(params, cfg.database_path);

    std::cerr << "[slam] RTAB-Map engine initialized (strategy="
              << cfg.odometry_strategy
              << ", loop_closure=" << cfg.loop_closure
              << ", db=" << cfg.database_path << ")" << std::endl;

    return engine;
}

static void destroy_slam_engine(SlamEngine &engine) {
    if (engine.rtabmap_engine) {
        engine.rtabmap_engine->close();
        delete engine.rtabmap_engine;
        engine.rtabmap_engine = nullptr;
    }
    if (engine.odometry) {
        delete engine.odometry;
        engine.odometry = nullptr;
    }
}

/* --------------------------------------------------------------------------
 * Pose extraction helpers
 * -------------------------------------------------------------------------- */

static void transform_to_pose_msg(
    const rtabmap::Transform &t,
    const cv::Mat &covariance,
    uint8_t confidence,
    uint8_t reset_counter,
    struct vslam_pose_msg &msg)
{
    using namespace std::chrono;
    auto now = system_clock::now();
    msg.timestamp_us = static_cast<uint64_t>(
        duration_cast<microseconds>(now.time_since_epoch()).count());

    msg.x = t.x();
    msg.y = t.y();
    msg.z = t.z();

    /* Extract Euler angles from rotation matrix. */
    float roll, pitch, yaw;
    t.getEulerAngles(roll, pitch, yaw);
    msg.roll = roll;
    msg.pitch = pitch;
    msg.yaw = yaw;

    msg.confidence = confidence;
    msg.reset_counter = reset_counter;

    /* Fill upper triangle of 6×6 covariance → 21 floats. */
    memset(msg.covariance, 0, sizeof(msg.covariance));
    if (!covariance.empty() && covariance.rows == 6 && covariance.cols == 6) {
        int idx = 0;
        for (int r = 0; r < 6; ++r) {
            for (int c = r; c < 6; ++c) {
                msg.covariance[idx++] =
                    static_cast<float>(covariance.at<double>(r, c));
            }
        }
    }
}

/* --------------------------------------------------------------------------
 * Unix socket server
 * -------------------------------------------------------------------------- */

struct SocketServer {
    int listen_fd = -1;
    int client_fd = -1;
    std::string path;
};

static bool socket_server_init(SocketServer &srv, const std::string &sock_path) {
    srv.path = sock_path;

    /* Ensure parent directory exists. */
    std::string parent = sock_path.substr(0, sock_path.rfind('/'));
    if (!parent.empty()) {
        /* Best-effort mkdir. */
        mkdir(parent.c_str(), 0755);
    }

    /* Remove stale socket. */
    unlink(sock_path.c_str());

    srv.listen_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (srv.listen_fd < 0) {
        perror("[socket] socket()");
        return false;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    if (sock_path.size() >= sizeof(addr.sun_path)) {
        std::cerr << "[socket] Path too long: " << sock_path << std::endl;
        close(srv.listen_fd);
        srv.listen_fd = -1;
        return false;
    }
    strncpy(addr.sun_path, sock_path.c_str(), sizeof(addr.sun_path) - 1);

    if (bind(srv.listen_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("[socket] bind()");
        close(srv.listen_fd);
        srv.listen_fd = -1;
        return false;
    }

    /* Allow group read/write for the bridge process. */
    chmod(sock_path.c_str(), 0660);

    if (listen(srv.listen_fd, 1) < 0) {
        perror("[socket] listen()");
        close(srv.listen_fd);
        srv.listen_fd = -1;
        return false;
    }

    std::cerr << "[socket] Listening on " << sock_path << std::endl;
    return true;
}

/**
 * Accept a client if none is connected.  Non-blocking.
 */
static void socket_accept_nonblock(SocketServer &srv) {
    if (srv.client_fd >= 0 || srv.listen_fd < 0)
        return;

    /* Set non-blocking for accept. */
    fd_set rfds;
    FD_ZERO(&rfds);
    FD_SET(srv.listen_fd, &rfds);
    struct timeval tv = {0, 0}; /* instant poll */

    int ret = select(srv.listen_fd + 1, &rfds, nullptr, nullptr, &tv);
    if (ret > 0) {
        srv.client_fd = accept(srv.listen_fd, nullptr, nullptr);
        if (srv.client_fd >= 0) {
            std::cerr << "[socket] Client connected (fd="
                      << srv.client_fd << ")" << std::endl;
        }
    }
}

/**
 * Send a pose message to the connected client.
 * Returns false if send fails (client disconnected).
 */
static bool socket_send_pose(SocketServer &srv,
                             const struct vslam_pose_msg &msg) {
    if (srv.client_fd < 0)
        return true; /* No client, nothing to do. */

    ssize_t n = write(srv.client_fd, &msg, sizeof(msg));
    if (n != sizeof(msg)) {
        std::cerr << "[socket] Client disconnected" << std::endl;
        close(srv.client_fd);
        srv.client_fd = -1;
        return false;
    }
    return true;
}

static void socket_server_close(SocketServer &srv) {
    if (srv.client_fd >= 0) {
        close(srv.client_fd);
        srv.client_fd = -1;
    }
    if (srv.listen_fd >= 0) {
        close(srv.listen_fd);
        srv.listen_fd = -1;
    }
    if (!srv.path.empty()) {
        unlink(srv.path.c_str());
    }
}

/* --------------------------------------------------------------------------
 * Main SLAM loop
 * -------------------------------------------------------------------------- */

static void run_slam_loop(
    DaiPipeline &dai,
    SlamEngine &engine,
    SocketServer &srv,
    const SlamConfig &cfg)
{
    /* Rate limiter for pose output. */
    const auto pose_interval = std::chrono::microseconds(
        1000000 / cfg.pose_output_rate_hz);
    auto last_pose_time = std::chrono::steady_clock::now();

    /* Watchdog interval: send every 15 seconds (WatchdogSec=30). */
    auto last_watchdog = std::chrono::steady_clock::now();
    const auto watchdog_interval = std::chrono::seconds(15);

    uint64_t frame_count = 0;

    /* Get baseline calibration for camera model. */
    auto calib = dai.device->readCalibration();
    auto intrinsics_left = calib.getCameraIntrinsics(
        dai::CameraBoardSocket::CAM_B);
    auto intrinsics_right = calib.getCameraIntrinsics(
        dai::CameraBoardSocket::CAM_C);
    double baseline = calib.getBaselineDistance(
        dai::CameraBoardSocket::CAM_B, dai::CameraBoardSocket::CAM_C) / 100.0;

    /* Get image size from first left frame. */
    int img_width = 640;
    int img_height = 400;
    {
        auto left_frame = dai.left_queue->get<dai::ImgFrame>();
        if (left_frame) {
            img_width = left_frame->getWidth();
            img_height = left_frame->getHeight();
            std::cerr << "[slam] Image size: " << img_width << "x"
                      << img_height << std::endl;
        }
    }

    /* Build stereo camera model. */
    double fx_l = intrinsics_left[0][0];
    double fy_l = intrinsics_left[1][1];
    double cx_l = intrinsics_left[0][2];
    double cy_l = intrinsics_left[1][2];
    double fx_r = intrinsics_right[0][0];
    double cx_r = intrinsics_right[0][2];

    rtabmap::CameraModel left_model(
        fx_l, fy_l, cx_l, cy_l,
        rtabmap::Transform::getIdentity(),
        0, cv::Size(img_width, img_height));

    rtabmap::CameraModel right_model(
        fx_r, fy_l, cx_r, cy_l,
        rtabmap::Transform::getIdentity(),
        0, cv::Size(img_width, img_height));

    rtabmap::StereoCameraModel stereo_model(
        "oakd", left_model, right_model,
        rtabmap::Transform(
            1, 0, 0, baseline,
            0, 1, 0, 0,
            0, 0, 1, 0));

    std::cerr << "[slam] Entering main loop (pose_rate="
              << cfg.pose_output_rate_hz << " Hz)" << std::endl;

    while (!g_shutdown.load()) {
        /* Accept new clients. */
        socket_accept_nonblock(srv);

        /* Get stereo frames. */
        auto left_data = dai.left_queue->tryGet<dai::ImgFrame>();
        auto right_data = dai.right_queue->tryGet<dai::ImgFrame>();

        if (!left_data || !right_data) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }

        /* Convert to OpenCV. */
        cv::Mat left_img = left_data->getCvFrame();
        cv::Mat right_img = right_data->getCvFrame();

        if (left_img.empty() || right_img.empty())
            continue;

        frame_count++;

        /* Drain IMU data (consume but we pass the latest accel/gyro to
         * SensorData for RTAB-Map's IMU integration). */
        cv::Vec3f accel(0, 0, 0);
        cv::Vec3f gyro(0, 0, 0);
        {
            auto imu_data = dai.imu_queue->tryGetAll<dai::IMUData>();
            for (auto &pkt : imu_data) {
                for (auto &p : pkt->packets) {
                    accel[0] = p.acceleroMeter.x;
                    accel[1] = p.acceleroMeter.y;
                    accel[2] = p.acceleroMeter.z;
                    gyro[0] = p.gyroscope.x;
                    gyro[1] = p.gyroscope.y;
                    gyro[2] = p.gyroscope.z;
                }
            }
        }

        /* Build SensorData for RTAB-Map. */
        double stamp = static_cast<double>(
            std::chrono::duration_cast<std::chrono::microseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count())
            / 1e6;

        rtabmap::SensorData sensor_data(
            left_img, right_img, stereo_model, 0, stamp);

        /* Set IMU data if available. */
        if (accel[0] != 0 || accel[1] != 0 || accel[2] != 0) {
            rtabmap::Transform imu_local_transform = rtabmap::Transform::getIdentity();
            sensor_data.setIMU(rtabmap::IMU(
                gyro, cv::Mat::eye(3, 3, CV_64FC1),
                accel, cv::Mat::eye(3, 3, CV_64FC1),
                imu_local_transform));
        }

        /* Run odometry. */
        rtabmap::OdometryInfo odom_info;
        rtabmap::Transform pose = engine.odometry->process(sensor_data, &odom_info);

        if (pose.isNull()) {
            /* Odometry lost — increment reset counter. */
            if (odom_info.lost) {
                engine.odometry->reset();
                engine.reset_counter++;
                std::cerr << "[slam] Odometry lost, reset #"
                          << (int)engine.reset_counter << std::endl;
            }
            continue;
        }

        /* Feed to RTAB-Map for loop closure / graph optimization. */
        if (engine.rtabmap_engine) {
            engine.rtabmap_engine->process(sensor_data, pose);
        }

        /* Rate-limit pose output. */
        auto now = std::chrono::steady_clock::now();
        if (now - last_pose_time < pose_interval)
            continue;
        last_pose_time = now;

        /* Build pose message. */
        struct vslam_pose_msg msg;
        memset(&msg, 0, sizeof(msg));

        uint8_t confidence = 0;
        if (odom_info.inliers > 0) {
            confidence = static_cast<uint8_t>(
                std::min(100, odom_info.inliers));
        }

        transform_to_pose_msg(
            pose, odom_info.covariance,
            confidence, engine.reset_counter, msg);

        /* Send over socket. */
        socket_send_pose(srv, msg);

        /* Periodic logging. */
        if (frame_count % 100 == 0) {
            std::cerr << "[slam] frames=" << frame_count
                      << " confidence=" << (int)msg.confidence
                      << " resets=" << (int)msg.reset_counter
                      << std::endl;
        }

        /* Watchdog. */
        if (now - last_watchdog >= watchdog_interval) {
            sd_notify(0, "WATCHDOG=1");
            last_watchdog = now;
        }
    }
}

/* --------------------------------------------------------------------------
 * main
 * -------------------------------------------------------------------------- */

static void print_usage(const char *argv0) {
    std::cerr << "Usage: " << argv0 << " --config <path>" << std::endl;
}

int main(int argc, char *argv[]) {
    /* Parse --config argument. */
    std::string config_path;
    for (int i = 1; i < argc; ++i) {
        std::string arg(argv[i]);
        if (arg == "--config" && i + 1 < argc) {
            config_path = argv[++i];
        } else if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            return 0;
        } else {
            std::cerr << "Unknown argument: " << arg << std::endl;
            print_usage(argv[0]);
            return 1;
        }
    }

    /* Install signal handlers. */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = signal_handler;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, nullptr);
    sigaction(SIGINT, &sa, nullptr);

    /* Load configuration. */
    SlamConfig cfg = load_config(config_path);

    std::cerr << "[main] rtabmap_slam_node starting" << std::endl;
    std::cerr << "[main] socket_path=" << cfg.socket_path << std::endl;
    std::cerr << "[main] stereo=" << cfg.stereo_resolution
              << "@" << cfg.stereo_fps << "fps"
              << " imu=" << cfg.imu_rate_hz << "Hz" << std::endl;

    /* Initialize Unix socket server. */
    SocketServer srv;
    if (!socket_server_init(srv, cfg.socket_path)) {
        std::cerr << "[main] Failed to create socket server" << std::endl;
        return 1;
    }

    /* Initialize depthai pipeline. */
    DaiPipeline dai;
    try {
        dai = create_depthai_pipeline(cfg);
    } catch (const std::exception &e) {
        std::cerr << "[main] DepthAI init failed: " << e.what() << std::endl;
        socket_server_close(srv);
        return 1;
    }

    /* Initialize RTAB-Map. */
    SlamEngine engine = create_slam_engine(cfg);

    /* Notify systemd we are ready. */
    sd_notify(0, "READY=1");
    std::cerr << "[main] sd_notify READY=1 sent" << std::endl;

    /* Run the main SLAM loop. */
    run_slam_loop(dai, engine, srv, cfg);

    /* Cleanup. */
    std::cerr << "[main] Shutting down..." << std::endl;
    sd_notify(0, "STOPPING=1");

    destroy_slam_engine(engine);
    socket_server_close(srv);

    std::cerr << "[main] Clean exit" << std::endl;
    return 0;
}
