cmake_minimum_required(VERSION 3.16)
project(rtabmap_slam_node LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

find_package(RTABMap REQUIRED COMPONENTS core utilite)
find_package(depthai REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgproc)
find_package(PkgConfig REQUIRED)

pkg_check_modules(SYSTEMD REQUIRED libsystemd)
pkg_check_modules(YAMLCPP REQUIRED yaml-cpp)

# ---------------------------------------------------------------------------
# Build the SLAM node binary
# ---------------------------------------------------------------------------

add_executable(rtabmap_slam_node
    src/rtabmap_slam_node.cpp
)

target_include_directories(rtabmap_slam_node PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${RTABMap_INCLUDE_DIRS}
    ${OpenCV_INCLUDE_DIRS}
    ${SYSTEMD_INCLUDE_DIRS}
    ${YAMLCPP_INCLUDE_DIRS}
)

target_link_libraries(rtabmap_slam_node PRIVATE
    rtabmap::core
    rtabmap::utilite
    depthai::core
    ${OpenCV_LIBS}
    ${SYSTEMD_LIBRARIES}
    ${YAMLCPP_LIBRARIES}
)

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

install(TARGETS rtabmap_slam_node
    RUNTIME DESTINATION bin
)
