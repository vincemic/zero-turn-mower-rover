/*
 * gpu-egl-ready.c — Minimal EGL device probe for NVIDIA Tegra.
 * Exit 0 = ready, Exit 1 = not ready, Exit 2 = fatal (missing libEGL).
 * Build: gcc -O2 -o gpu-egl-ready gpu-egl-ready.c -lEGL
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <stdio.h>

#ifndef EGL_PLATFORM_DEVICE_EXT
#define EGL_PLATFORM_DEVICE_EXT 0x313F
#endif

int main(void) {
    PFNEGLQUERYDEVICESEXTPROC eglQueryDevicesEXT =
        (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC eglGetPlatformDisplayEXT =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");

    if (!eglQueryDevicesEXT || !eglGetPlatformDisplayEXT) {
        fprintf(stderr, "gpu-egl-ready: EGL device extensions unavailable\n");
        return 2;
    }

    EGLDeviceEXT devices[4];
    EGLint num_devices = 0;
    if (!eglQueryDevicesEXT(4, devices, &num_devices) || num_devices == 0)
        return 1;

    EGLDisplay dpy = eglGetPlatformDisplayEXT(
        EGL_PLATFORM_DEVICE_EXT, devices[0], NULL);
    if (dpy == EGL_NO_DISPLAY) return 1;

    EGLint major, minor;
    if (!eglInitialize(dpy, &major, &minor)) return 1;

    eglTerminate(dpy);
    return 0;
}
