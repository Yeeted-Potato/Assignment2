package nz.ac.aut.comp713.customerorders.location;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.location.Criteria;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Handler;
import android.os.Looper;

import java.util.List;

/**
 * Week 9 mobile capability: a single coarse FOREGROUND location fix, with a
 * manual fallback left entirely to the caller.
 *
 * Rules this class follows, straight from the Week 9 material:
 *   - only coarse foreground location is requested; never background location
 *   - a fix is best-effort and may be missing, stale or slow
 *   - when no usable fix exists the caller is TOLD, and must let the user type
 *     a delivery address instead
 *   - coordinates are never invented or guessed
 *   - the request is one-shot, not a continuous stream, and is cancelled when
 *     the screen goes away
 */
public final class LocationHelper {

    /** Reasons a fix could not be supplied, so each screen shows the right message. */
    public static final int REASON_PERMISSION_DENIED = 1;
    public static final int REASON_SERVICES_DISABLED = 2;
    public static final int REASON_TIMEOUT = 3;
    public static final int REASON_NO_FIX = 4;
    public static final int REASON_STALE_ONLY = 5;

    /** Must match the request code checked in Activity.onRequestPermissionsResult. */
    public static final int PERMISSION_REQUEST_CODE = 4201;

    /** A cached fix older than this is treated as stale and deliberately not used. */
    private static final long STALE_AFTER_MS = 2 * 60 * 1000L;

    /** How long to wait for a fresh one-shot fix before giving up. */
    private static final long FIX_TIMEOUT_MS = 10 * 1000L;

    public interface Callback {
        void onLocationReady(Location location);

        void onUnavailable(int reason);
    }

    private final Activity activity;
    private final LocationManager locationManager;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private LocationListener activeListener;
    private Runnable timeoutRunnable;
    private boolean finished;

    @SuppressWarnings("deprecation")
    public LocationHelper(Activity activity) {
        this.activity = activity;
        this.locationManager = (LocationManager) activity.getSystemService(Activity.LOCATION_SERVICE);
    }

    public boolean hasLocationPermission() {
        return activity.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
                    == PackageManager.PERMISSION_GRANTED
                || activity.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                    == PackageManager.PERMISSION_GRANTED;
    }

    /** Asks for coarse foreground location only. The answer arrives in onRequestPermissionsResult. */
    public void requestLocationPermission() {
        activity.requestPermissions(
                new String[]{Manifest.permission.ACCESS_COARSE_LOCATION},
                PERMISSION_REQUEST_CODE);
    }

    /** False when the user has turned location off at the device level. */
    public boolean isAnyProviderEnabled() {
        return locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)
                || locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
    }

    /**
     * Tries to obtain one usable position. Exactly one of the callback methods
     * is called, always on the main thread.
     */
    public void requestFix(final Callback callback) {
        finished = false;

        // 1. Permission: the app must never silently continue without it.
        if (!hasLocationPermission()) {
            callback.onUnavailable(REASON_PERMISSION_DENIED);
            return;
        }

        // 2. Location services switched off at the device level.
        if (!isAnyProviderEnabled()) {
            callback.onUnavailable(REASON_SERVICES_DISABLED);
            return;
        }

        // 3. A recent cached fix is good enough and avoids waiting for a new one.
        Location cached = bestLastKnown();
        boolean sawStaleFix = cached != null;
        if (cached != null && !isStale(cached)) {
            finished = true;
            callback.onLocationReady(cached);
            return;
        }

        // 4. Otherwise ask for exactly one fresh fix.
        String provider = bestEnabledProvider();
        if (provider == null) {
            finished = true;
            callback.onUnavailable(REASON_NO_FIX);
            return;
        }

        timeoutRunnable = new Runnable() {
            @Override
            public void run() {
                boolean staleOnly = sawStaleFix;
                stopUpdates();
                if (!finished) {
                    finished = true;
                    callback.onUnavailable(staleOnly ? REASON_STALE_ONLY : REASON_TIMEOUT);
                }
            }
        };
        mainHandler.postDelayed(timeoutRunnable, FIX_TIMEOUT_MS);

        activeListener = new LocationListener() {
            @Override
            public void onLocationChanged(Location location) {
                if (finished) {
                    return;
                }
                finished = true;
                stopUpdates();
                callback.onLocationReady(location);
            }
        };

        try {
            // One-shot request rather than a continuous location stream.
            locationManager.requestSingleUpdate(provider, activeListener, Looper.getMainLooper());
        } catch (SecurityException e) {
            // Permission was revoked between the check above and this call.
            stopUpdates();
            if (!finished) {
                finished = true;
                callback.onUnavailable(REASON_PERMISSION_DENIED);
            }
        } catch (IllegalArgumentException e) {
            // The chosen provider disappeared; there is no fix to be had.
            stopUpdates();
            if (!finished) {
                finished = true;
                callback.onUnavailable(REASON_NO_FIX);
            }
        }
    }

    /** Stops any in-flight request. Call this from Activity.onStop() or onDestroy(). */
    public void cancel() {
        finished = true;
        stopUpdates();
    }

    private void stopUpdates() {
        if (timeoutRunnable != null) {
            mainHandler.removeCallbacks(timeoutRunnable);
            timeoutRunnable = null;
        }
        if (activeListener != null) {
            try {
                locationManager.removeUpdates(activeListener);
            } catch (SecurityException ignored) {
                // Nothing to clean up if the permission has already gone.
            }
            activeListener = null;
        }
    }

    /** The most recent fix any provider holds, or null if none exists at all. */
    private Location bestLastKnown() {
        Location best = null;
        List<String> providers = locationManager.getAllProviders();
        for (int i = 0; i < providers.size(); i++) {
            try {
                Location location = locationManager.getLastKnownLocation(providers.get(i));
                if (location != null && (best == null || location.getTime() > best.getTime())) {
                    best = location;
                }
            } catch (SecurityException ignored) {
                // Skip a provider we are not allowed to read.
            } catch (IllegalArgumentException ignored) {
                // Skip a provider that no longer exists.
            }
        }
        return best;
    }

    private String bestEnabledProvider() {
        Criteria criteria = new Criteria();
        criteria.setAccuracy(Criteria.ACCURACY_COARSE);
        String provider = locationManager.getBestProvider(criteria, true);
        return provider != null ? provider : LocationManager.NETWORK_PROVIDER;
    }

    /** Week 9: stale data must be detected rather than presented as current. */
    private static boolean isStale(Location location) {
        return Math.abs(System.currentTimeMillis() - location.getTime()) > STALE_AFTER_MS;
    }
}
