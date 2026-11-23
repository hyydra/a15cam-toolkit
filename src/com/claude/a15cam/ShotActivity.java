package com.claude.a15cam;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.Log;
import android.util.Range;
import android.util.Size;
import android.view.Surface;
import android.view.WindowManager;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.util.Arrays;

/**
 * Fejnelkuli Camera2 felvetel (Claude Code, 2026-11-22). Inditas: adb shell am start -n com.claude.a15cam/.ShotActivity
 *   --es out nev.jpg  --ei iso 800  --el exp_us 33333  [--es cam 0] [--es size 4000x3000] [--ef focus 0.0] [--ez list true]
 * A kimenet a getExternalFilesDir(null) mappaba kerul (/sdcard/Android/data/com.claude.a15cam/files/), mellette nev.jpg.txt allapot.
 * iso/exp_us nelkul automatikus expozicio. A telefon kepernyoje legyen bekapcsolva (az Activity elo elterben fut).
 */
public class ShotActivity extends Activity {
    static final String TAG = "A15Cam";
    CameraDevice cam;
    CameraCaptureSession sess;
    ImageReader jpeg, yuv;
    HandlerThread ht;
    Handler h;
    File dir;
    String outName = "shot.jpg";
    boolean done = false;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        ht = new HandlerThread("a15cam");
        ht.start();
        h = new Handler(ht.getLooper());
        dir = getExternalFilesDir(null);
        Intent in = getIntent();
        String o = in.getStringExtra("out");
        if (o != null && !o.isEmpty()) outName = new File(o).getName();
        new Handler(Looper.getMainLooper()).postDelayed(() -> fail("idotullepes"), in.getIntExtra("timeout_s", 40) * 1000L);
        if (checkSelfPermission(android.Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            fail("nincs CAMERA engedely (adb shell pm grant com.claude.a15cam android.permission.CAMERA)");
            return;
        }
        try {
            start(in);
        } catch (Throwable t) {
            fail("start: " + t);
        }
    }

    void status(String s) {
        Log.i(TAG, s);
        try (FileOutputStream f = new FileOutputStream(new File(dir, outName + ".txt"))) {
            f.write((s + "\n").getBytes());
        } catch (Exception ignored) {
        }
    }

    void fail(String why) {
        if (done) return;
        done = true;
        status("HIBA: " + why);
        finish();
    }

    void start(Intent in) throws CameraAccessException {
        CameraManager m = (CameraManager) getSystemService(Context.CAMERA_SERVICE);
        String id = in.getStringExtra("cam");
        if (id == null) id = "0";
        CameraCharacteristics cc = m.getCameraCharacteristics(id);
        StreamConfigurationMap map = cc.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        Size[] sizes = map.getOutputSizes(ImageFormat.JPEG);
        Range<Integer> isoR = cc.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE);
        Range<Long> expR = cc.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE);

        if (in.getBooleanExtra("list", false)) {
            StringBuilder sb = new StringBuilder();
            try {
                for (String c : m.getCameraIdList()) sb.append("kamera ").append(c).append("\n");
            } catch (Throwable ignored) {
            }
            sb.append("id=").append(id).append(" iso=").append(isoR).append(" exp_ns=").append(expR).append("\n");
            Size[] top = sizes.clone();
            Arrays.sort(top, (a, c) -> Long.compare((long) c.getWidth() * c.getHeight(), (long) a.getWidth() * a.getHeight()));
            for (int i = 0; i < Math.min(6, top.length); i++) sb.append("meret ").append(top[i]).append("\n");
            try {
                int[] caps = cc.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
                sb.append("caps=").append(Arrays.toString(caps)).append("\n");
                Size[] rs = map.getOutputSizes(ImageFormat.RAW_SENSOR);
                sb.append("raw_sensor=").append(rs == null ? "none" : Arrays.toString(rs)).append("\n");
                Size[] r10 = map.getOutputSizes(ImageFormat.RAW10);
                sb.append("raw10=").append(r10 == null ? "none" : Arrays.toString(r10)).append("\n");
            } catch (Throwable t) {
                sb.append("rawinfo err ").append(t).append("\n");
            }
            try {
                java.util.List<Integer> ex = m.getCameraExtensionCharacteristics(id).getSupportedExtensions();
                sb.append("extensions=").append(ex).append(" (1=AUTOMATIC 2=BOKEH 3=HDR 4=NIGHT 5=FACE_RETOUCH)\n");
            } catch (Throwable t) {
                sb.append("extensions err ").append(t).append("\n");
            }
            sb.append("sensor_orientation=").append(cc.get(CameraCharacteristics.SENSOR_ORIENTATION)).append("\n");
            done = true;
            status(sb.toString());
            finish();
            return;
        }

        Size pick = null;
        String sz = in.getStringExtra("size");
        if (sz != null && sz.contains("x")) {
            String[] p = sz.split("x");
            pick = new Size(Integer.parseInt(p[0]), Integer.parseInt(p[1]));
        } else {
            long best = 0;
            for (Size s : sizes) {
                long a = (long) s.getWidth() * s.getHeight();
                if (a <= 13_000_000L && a > best) {
                    best = a;
                    pick = s;
                }
            }
            if (pick == null) pick = sizes[sizes.length - 1];
        }
        final Size jsize = pick;
        final int orient = cc.get(CameraCharacteristics.SENSOR_ORIENTATION);
        final boolean manual = in.hasExtra("iso") || in.hasExtra("exp_us");
        final int iso = isoR == null ? 100 : Math.max(isoR.getLower(), Math.min(isoR.getUpper(), in.getIntExtra("iso", 400)));
        final long expNs = expR == null ? 10_000_000L : Math.max(expR.getLower(), Math.min(expR.getUpper(), in.getLongExtra("exp_us", 16666) * 1000L));
        final boolean hasFocus = in.hasExtra("focus");
        final float focus = in.getFloatExtra("focus", 0f);

        jpeg = ImageReader.newInstance(jsize.getWidth(), jsize.getHeight(), ImageFormat.JPEG, 2);
        yuv = ImageReader.newInstance(640, 480, ImageFormat.YUV_420_888, 2);
        yuv.setOnImageAvailableListener(r -> {
            Image i = r.acquireLatestImage();
            if (i != null) i.close();
        }, h);
        jpeg.setOnImageAvailableListener(r -> {
            Image i = r.acquireLatestImage();
            if (i == null) return;
            try {
                ByteBuffer bb = i.getPlanes()[0].getBuffer();
                byte[] bytes = new byte[bb.remaining()];
                bb.get(bytes);
                try (FileOutputStream f = new FileOutputStream(new File(dir, outName))) {
                    f.write(bytes);
                }
                if (!done) {
                    done = true;
                    status("OK " + outName + " " + bytes.length + " bajt " + jsize + (manual ? " iso=" + iso + " exp_us=" + (expNs / 1000) : " auto"));
                }
            } catch (Throwable t) {
                fail("mentes: " + t);
                return;
            } finally {
                i.close();
            }
            runOnUiThread(this::finish);
        }, h);

        m.openCamera(id, new CameraDevice.StateCallback() {
            @Override
            public void onOpened(CameraDevice d) {
                cam = d;
                try {
                    d.createCaptureSession(Arrays.asList(yuv.getSurface(), jpeg.getSurface()), new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession s) {
                            sess = s;
                            try {
                                CaptureRequest.Builder pv = d.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                pv.addTarget(yuv.getSurface());
                                CaptureRequest.Builder st = d.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
                                st.addTarget(jpeg.getSurface());
                                for (CaptureRequest.Builder bb : new CaptureRequest.Builder[]{pv, st}) {
                                    bb.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE);
                                    if (manual) {
                                        bb.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
                                        bb.set(CaptureRequest.SENSOR_SENSITIVITY, iso);
                                        bb.set(CaptureRequest.SENSOR_EXPOSURE_TIME, expNs);
                                    }
                                    if (hasFocus) {
                                        bb.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF);
                                        bb.set(CaptureRequest.LENS_FOCUS_DISTANCE, focus);
                                    }
                                }
                                st.set(CaptureRequest.JPEG_ORIENTATION, orient);
                                st.set(CaptureRequest.JPEG_QUALITY, (byte) 95);
                                s.setRepeatingRequest(pv.build(), null, h);
                                h.postDelayed(() -> {
                                    try {
                                        s.capture(st.build(), null, h);
                                    } catch (Throwable t) {
                                        fail("capture: " + t);
                                    }
                                }, 1800);
                            } catch (Throwable t) {
                                fail("keres: " + t);
                            }
                        }

                        @Override
                        public void onConfigureFailed(CameraCaptureSession s) {
                            fail("session konfiguracio sikertelen");
                        }
                    }, h);
                } catch (Throwable t) {
                    fail("session: " + t);
                }
            }

            @Override
            public void onDisconnected(CameraDevice d) {
                fail("kamera lecsatlakozott");
            }

            @Override
            public void onError(CameraDevice d, int e) {
                fail("kamera hiba " + e);
            }
        }, h);
    }

    @Override
    protected void onDestroy() {
        try {
            if (sess != null) sess.close();
            if (cam != null) cam.close();
            if (jpeg != null) jpeg.close();
            if (yuv != null) yuv.close();
            if (ht != null) ht.quitSafely();
        } catch (Throwable ignored) {
        }
        super.onDestroy();
    }
}
