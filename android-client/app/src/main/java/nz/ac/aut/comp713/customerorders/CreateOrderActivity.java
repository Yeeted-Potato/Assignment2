package nz.ac.aut.comp713.customerorders;

import android.app.Activity;
import android.content.pm.PackageManager;
import android.location.Location;
import android.os.Bundle;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import nz.ac.aut.comp713.customerorders.api.ApiClient;
import nz.ac.aut.comp713.customerorders.api.ApiException;
import nz.ac.aut.comp713.customerorders.location.LocationHelper;
import nz.ac.aut.comp713.customerorders.model.Product;

/**
 * Screen 3 of 3: place an order, including the mobile capability.
 *
 * Mobile capability (Week 9): the delivery destination can be captured from
 * the device's coarse foreground location, with a typed address as the manual
 * fallback. The rules the app follows are:
 *   - the position is only ever real; it is never invented or approximated
 *   - if permission is denied, location services are off, the fix is stale or
 *     no fix arrives in time, the user is told and can type an address instead
 *   - at least one of (device location, typed address) is required, which is
 *     the same rule the API enforces
 *
 * Both values are sent to the API and stored on the order, so staff on the web
 * client can see where the delivery is going.
 */
public class CreateOrderActivity extends Activity {

    public static final String EXTRA_CUSTOMER_ID = "extra_customer_id";

    private static final String STATE_QUANTITY = "state_quantity";
    private static final String STATE_ADDRESS = "state_address";
    private static final String STATE_LATITUDE = "state_latitude";
    private static final String STATE_LONGITUDE = "state_longitude";
    private static final String STATE_LOCATION_STATUS = "state_location_status";
    private static final String STATE_LOCATION_COLOUR = "state_location_colour";

    private int customerId;

    private Spinner productSpinner;
    private EditText quantityInput;
    private Button useLocationButton;
    private TextView locationStatusView;
    private EditText addressInput;
    private Button placeOrderButton;
    private ProgressBar progress;
    private TextView statusView;

    private final List<Product> products = new ArrayList<>();
    private ArrayAdapter<Product> productAdapter;

    private LocationHelper locationHelper;

    /** Captured device position. Null means "use the typed address instead". */
    private Double latitude;
    private Double longitude;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_create_order);

        customerId = getIntent().getIntExtra(EXTRA_CUSTOMER_ID, -1);

        productSpinner = findViewById(R.id.productSpinner);
        quantityInput = findViewById(R.id.quantityInput);
        useLocationButton = findViewById(R.id.useLocationButton);
        locationStatusView = findViewById(R.id.locationStatusView);
        addressInput = findViewById(R.id.addressInput);
        placeOrderButton = findViewById(R.id.placeOrderButton);
        progress = findViewById(R.id.progress);
        statusView = findViewById(R.id.statusView);

        locationHelper = new LocationHelper(this);

        productAdapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, products);
        productAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        productSpinner.setAdapter(productAdapter);

        if (savedInstanceState != null) {
            quantityInput.setText(savedInstanceState.getString(STATE_QUANTITY, ""));
            addressInput.setText(savedInstanceState.getString(STATE_ADDRESS, ""));
            locationStatusView.setText(savedInstanceState.getString(STATE_LOCATION_STATUS, ""));
            locationStatusView.setTextColor(savedInstanceState.getInt(STATE_LOCATION_COLOUR,
                    getColor(R.color.text_secondary)));
            if (savedInstanceState.containsKey(STATE_LATITUDE)) {
                latitude = savedInstanceState.getDouble(STATE_LATITUDE);
                longitude = savedInstanceState.getDouble(STATE_LONGITUDE);
            }
        }

        useLocationButton.setOnClickListener(v -> useMyLocation());
        placeOrderButton.setOnClickListener(v -> placeOrder());

        loadProducts();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        outState.putString(STATE_QUANTITY, quantityInput.getText().toString());
        outState.putString(STATE_ADDRESS, addressInput.getText().toString());
        outState.putString(STATE_LOCATION_STATUS, locationStatusView.getText().toString());
        outState.putInt(STATE_LOCATION_COLOUR, locationStatusView.getCurrentTextColor());
        if (latitude != null) {
            outState.putDouble(STATE_LATITUDE, latitude);
            outState.putDouble(STATE_LONGITUDE, longitude);
        }
    }

    @Override
    protected void onDestroy() {
        // Never leave a location request running against a dead screen.
        locationHelper.cancel();
        super.onDestroy();
    }

    // ---------------------------------------------------------------- product

    private void loadProducts() {
        setLoading(true);

        ApiClient.executor().execute(() -> {
            try {
                String body = ApiClient.get("/products");
                final List<Product> loaded = new ArrayList<>();
                JSONArray array = new JSONArray(body);
                for (int i = 0; i < array.length(); i++) {
                    loaded.add(Product.fromJson(array.getJSONObject(i)));
                }

                runOnUiThread(() -> {
                    if (isDestroyed()) {
                        return;
                    }
                    products.clear();
                    products.addAll(loaded);
                    productAdapter.notifyDataSetChanged();
                    setLoading(false);
                    if (products.isEmpty()) {
                        statusView.setText(R.string.create_products_empty);
                    }
                });
            } catch (ApiException e) {
                showFailure(e.getMessage());
            } catch (IOException e) {
                showFailure(getString(R.string.error_network));
            } catch (JSONException e) {
                showFailure(getString(R.string.error_unexpected));
            }
        });
    }

    // -------------------------------------------------------------- location

    private void useMyLocation() {
        statusView.setText("");

        if (!locationHelper.hasLocationPermission()) {
            // The answer comes back to onRequestPermissionsResult below.
            locationStatusView.setText(R.string.location_permission_needed);
            locationHelper.requestLocationPermission();
            return;
        }
        requestFix();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != LocationHelper.PERMISSION_REQUEST_CODE) {
            return;
        }

        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            requestFix();
        } else {
            // Declined: fall back to the typed address, which is still a valid order.
            latitude = null;
            longitude = null;
            showLocationUnavailable(LocationHelper.REASON_PERMISSION_DENIED);
        }
    }

    private void requestFix() {
        locationStatusView.setTextColor(getColor(R.color.text_secondary));
        locationStatusView.setText(R.string.location_requesting);
        useLocationButton.setEnabled(false);

        // LocationHelper always calls back on the main thread.
        locationHelper.requestFix(new LocationHelper.Callback() {
            @Override
            public void onLocationReady(Location location) {
                if (isDestroyed()) {
                    return;
                }
                useLocationButton.setEnabled(true);
                latitude = location.getLatitude();
                longitude = location.getLongitude();
                locationStatusView.setTextColor(getColor(R.color.success));
                locationStatusView.setText(getString(R.string.location_captured,
                        latitude, longitude, location.getAccuracy()));
            }

            @Override
            public void onUnavailable(int reason) {
                if (isDestroyed()) {
                    return;
                }
                useLocationButton.setEnabled(true);
                showLocationUnavailable(reason);
            }
        });
    }

    /**
     * Every failure mode clears the coordinates and points the user at the
     * manual fallback, so a broken location never blocks an order.
     */
    private void showLocationUnavailable(int reason) {
        latitude = null;
        longitude = null;

        int message;
        switch (reason) {
            case LocationHelper.REASON_PERMISSION_DENIED:
                message = R.string.location_permission_denied;
                break;
            case LocationHelper.REASON_SERVICES_DISABLED:
                message = R.string.location_services_off;
                break;
            case LocationHelper.REASON_TIMEOUT:
                message = R.string.location_timeout;
                break;
            case LocationHelper.REASON_STALE_ONLY:
                message = R.string.location_stale;
                break;
            case LocationHelper.REASON_NO_FIX:
            default:
                message = R.string.location_unavailable;
                break;
        }

        locationStatusView.setTextColor(getColor(R.color.error));
        locationStatusView.setText(message);
    }

    // ----------------------------------------------------------------- order

    private void placeOrder() {
        statusView.setText("");

        if (products.isEmpty() || productSpinner.getSelectedItemPosition() < 0) {
            statusView.setText(R.string.create_no_product);
            return;
        }

        int quantity;
        try {
            quantity = Integer.parseInt(quantityInput.getText().toString().trim());
        } catch (NumberFormatException e) {
            statusView.setText(R.string.create_bad_quantity);
            return;
        }
        if (quantity < 1) {
            statusView.setText(R.string.create_bad_quantity);
            return;
        }

        // Same rule the API applies: a typed address OR a device position.
        String address = addressInput.getText().toString().trim();
        boolean hasLocation = latitude != null && longitude != null;
        if (address.isEmpty() && !hasLocation) {
            statusView.setText(R.string.create_missing_delivery);
            return;
        }

        final Product product = products.get(productSpinner.getSelectedItemPosition());
        final int finalQuantity = quantity;
        final String finalAddress = address;
        final Double finalLatitude = latitude;
        final Double finalLongitude = longitude;

        setLoading(true);

        ApiClient.executor().execute(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("product_id", product.id);
                body.put("quantity", finalQuantity);
                if (!finalAddress.isEmpty()) {
                    body.put("delivery_address", finalAddress);
                }
                if (finalLatitude != null && finalLongitude != null) {
                    body.put("latitude", finalLatitude.doubleValue());
                    body.put("longitude", finalLongitude.doubleValue());
                }

                ApiClient.post("/customers/" + customerId + "/orders", body.toString());

                runOnUiThread(() -> {
                    if (isDestroyed()) {
                        return;
                    }
                    setLoading(false);
                    statusView.setTextColor(getColor(R.color.success));
                    statusView.setText(R.string.create_placed);
                    // Return to the list, which re-reads from the API in onResume.
                    setResult(RESULT_OK);
                    finish();
                });
            } catch (ApiException e) {
                showFailure(e.getMessage());
            } catch (IOException e) {
                showFailure(getString(R.string.error_network));
            } catch (JSONException e) {
                showFailure(getString(R.string.error_unexpected));
            }
        });
    }

    private void showFailure(final String message) {
        runOnUiThread(() -> {
            if (isDestroyed()) {
                return;
            }
            setLoading(false);
            statusView.setTextColor(getColor(R.color.error));
            statusView.setText(message);
        });
    }

    private void setLoading(boolean loading) {
        progress.setVisibility(loading ? View.VISIBLE : View.GONE);
        placeOrderButton.setEnabled(!loading);
        useLocationButton.setEnabled(!loading);
        productSpinner.setEnabled(!loading);
    }
}
