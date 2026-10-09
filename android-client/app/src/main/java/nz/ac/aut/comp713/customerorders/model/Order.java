package nz.ac.aut.comp713.customerorders.model;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * An order from GET /customers/{id}/orders or POST /customers/{id}/orders.
 *
 * The API returns the order row on its own, so the product name is joined in
 * by the caller from GET /products. This matches what the web client already
 * does and keeps the Android branch free of backend changes.
 */
public final class Order {

    public final int id;
    public final int customerId;
    public final int productId;
    public final int quantity;
    public final String status;

    /** Typed by hand when the device could not supply a position. */
    public final String deliveryAddress;

    /** Supplied by the phone's location fix. Null when a typed address was used. */
    public final Double latitude;
    public final Double longitude;

    private Order(int id, int customerId, int productId, int quantity, String status,
                  String deliveryAddress, Double latitude, Double longitude) {
        this.id = id;
        this.customerId = customerId;
        this.productId = productId;
        this.quantity = quantity;
        this.status = status;
        this.deliveryAddress = deliveryAddress;
        this.latitude = latitude;
        this.longitude = longitude;
    }

    public static Order fromJson(JSONObject json) throws JSONException {
        return new Order(
                json.getInt("id"),
                json.getInt("customer_id"),
                json.getInt("product_id"),
                json.getInt("quantity"),
                json.getString("status"),
                json.isNull("delivery_address") ? null : json.getString("delivery_address"),
                json.isNull("latitude") ? null : json.getDouble("latitude"),
                json.isNull("longitude") ? null : json.getDouble("longitude"));
    }

    /** True when the order was placed with a device position rather than typed text. */
    public boolean hasDeviceLocation() {
        return latitude != null && longitude != null;
    }
}
