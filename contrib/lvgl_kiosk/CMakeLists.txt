cmake_minimum_required(VERSION 3.16)
project(mower_kiosk_renderer LANGUAGES C)

set(CMAKE_C_STANDARD 11)

find_package(PkgConfig REQUIRED)
pkg_check_modules(WAYLAND REQUIRED wayland-client)
pkg_check_modules(WAYLAND_CURSOR REQUIRED wayland-cursor)
pkg_check_modules(XKB REQUIRED xkbcommon)
pkg_check_modules(SYSTEMD REQUIRED libsystemd)

# Generate xdg-shell protocol headers required by LVGL's Wayland driver
find_program(WAYLAND_SCANNER wayland-scanner REQUIRED)
set(XDG_SHELL_XML "/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml")
set(WL_PROTO_DIR "${CMAKE_CURRENT_BINARY_DIR}/wayland-protocols")
file(MAKE_DIRECTORY ${WL_PROTO_DIR})
execute_process(
    COMMAND ${WAYLAND_SCANNER} client-header ${XDG_SHELL_XML}
            ${WL_PROTO_DIR}/wayland_xdg_shell.h
)
execute_process(
    COMMAND ${WAYLAND_SCANNER} private-code ${XDG_SHELL_XML}
            ${WL_PROTO_DIR}/wayland_xdg_shell.c
)

# Make protocol headers visible globally so LVGL's Wayland driver can find them
include_directories(${WL_PROTO_DIR})

include(FetchContent)
FetchContent_Declare(lvgl
    GIT_REPOSITORY https://github.com/lvgl/lvgl.git
    GIT_TAG        v9.5.0
)
FetchContent_MakeAvailable(lvgl)

# cJSON (single-file, vendored)
add_library(cjson STATIC src/cjson/cJSON.c)
target_include_directories(cjson PUBLIC src/cjson)

add_executable(mower-kiosk-renderer
    src/main.c
    src/socket_client.c
    src/json_parser.c
    src/theme.c
    src/widgets.c
    src/dashboard.c
    ${WL_PROTO_DIR}/wayland_xdg_shell.c
)
target_link_libraries(mower-kiosk-renderer PRIVATE
    lvgl cjson ${WAYLAND_LIBRARIES} ${WAYLAND_CURSOR_LIBRARIES} ${XKB_LIBRARIES} ${SYSTEMD_LIBRARIES}
)
target_include_directories(mower-kiosk-renderer PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}  # for lv_conf.h
    ${WAYLAND_INCLUDE_DIRS} ${XKB_INCLUDE_DIRS} ${SYSTEMD_INCLUDE_DIRS}
)
install(TARGETS mower-kiosk-renderer RUNTIME DESTINATION bin)
