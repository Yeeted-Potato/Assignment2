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

//gets one coarse foreground location fix from the phone
//if no fix is available the caller is told and the customer can type an address instead
public final class LocationHelper {

    //why a fix was not available, so each screen can show the right message
    public static final int REASON_PERMISSION_DENIED = 1;
    public static final int REASON_SERVICES_DISABLED = 2;
    public static final int REASON_TIMEOUT = 3;
    public static final int REASON_NO_FIX = 4;
    public static final int REASON_STALE_ONLY = 5;

    //must match the code checked in onRequestPermissionsResult
    public static final int PERMISSION_REQUEST_CODE = 4201;

    //a cached fix older than this counts as stale and is not used
    private static final long STALE_AFTER_MS = 2 * 60 * 1000L;

    //how long to wait for a fresh fix before giving up
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

    //asks for coarse foreground location only, the answer comes back to onRequestPermissionsResult
    public void requestLocationPermission() {
        activity.requestPermissions(
                new String[]{Manifest.permission.ACCESS_COARSE_LOCATION},
                PERMISSION_REQUEST_CODE);
    }

    //false when the user has turned location off on the device
    public boolean isAnyProviderEnabled() {
        return locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)
                || locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
    }

    //tries to get one usable position, always calls back on the main thread
    //requestSingleUpdate is deprecated but is the platform api the course teaches
    @SuppressWarnings("deprecation")
    public void requestFix(final Callback callback) {
        finished = false;

        //tell the caller if we do not have permission yet
        if (!hasLocationPermission()) {
            callback.onUnavailable(REASON_PERMISSION_DENIED);
            return;
        }

        //tell the caller if location is switched off
        if (!isAnyProviderEnabled()) {
            callback.onUnavailable(REASON_SERVICES_DISABLED);
            return;
        }

        //use a recent cached fix if there is one, no need to wait
        Location cached = bestLastKnown();
        boolean sawStaleFix = cached != null;
        if (cached != null && !isStale(cached)) {
            finished = true;
            callback.onLocationReady(cached);
            return;
        }

        //otherwise ask for one fresh fix
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
            //permission was revoked after the check above
            stopUpdates();
            if (!finished) {
                finished = true;
                callback.onUnavailable(REASON_PERMISSION_DENIED);
            }
        } catch (IllegalArgumentException e) {
            //the chosen provider is gone
            stopUpdates();
            if (!finished) {
                finished = true;
                callback.onUnavailable(REASON_NO_FIX);
            }
        }
    }

    //stops any request still running, called when the screen closes
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
                //nothing to clean up if the permission is already gone
            }
            activeListener = null;
        }
    }

    //the most recent fix any provider has, or null if there is none
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

    //getBestProvider is deprecated too but kept for the same reason as requestSingleUpdate
    @SuppressWarnings("deprecation")
    private String bestEnabledProvider() {
        Criteria criteria = new Criteria();
        criteria.setAccuracy(Criteria.ACCURACY_COARSE);
        String provider = locationManager.getBestProvider(criteria, true);
        return provider != null ? provider : LocationManager.NETWORK_PROVIDER;
    }

    //a stale fix must not be shown to the customer as if it were current
    private static boolean isStale(Location location) {
        return Math.abs(System.currentTimeMillis() - location.getTime()) > STALE_AFTER_MS;
    }
}
