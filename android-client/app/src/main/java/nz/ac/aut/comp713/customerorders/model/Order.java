package nz.ac.aut.comp713.customerorders.model;

import org.json.JSONException;
import org.json.JSONObject;

//an order, from get /customers/{id}/orders or post /customers/{id}/orders
//the product name is added by the caller from get /products
public final class Order {

    public final int id;
    public final int customerId;
    public final int productId;
    public final int quantity;
    public final String status;

    //typed by hand when the phone could not give a position
    public final String deliveryAddress;

    //from the phone's location, null when a typed address was used
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

    //true when the order used a position from the phone instead of typed text
    public boolean hasDeviceLocation() {
        return latitude != null && longitude != null;
    }
}
