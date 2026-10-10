package nz.ac.aut.comp713.customerorders.model;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.Locale;

//a product from get /products
public final class Product {

    public final int id;
    public final String name;
    public final double price;
    public final int stock;

    private Product(int id, String name, double price, int stock) {
        this.id = id;
        this.name = name;
        this.price = price;
        this.stock = stock;
    }

    public static Product fromJson(JSONObject json) throws JSONException {
        return new Product(
                json.getInt("id"),
                json.getString("name"),
                json.getDouble("price"),
                json.getInt("stock"));
    }

    //the text shown in the product spinner on the create order screen
    @Override
    public String toString() {
        return String.format(Locale.US, "%s - $%.2f (%d left)", name, price, stock);
    }
}
