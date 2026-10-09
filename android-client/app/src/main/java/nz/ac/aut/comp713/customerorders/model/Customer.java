package nz.ac.aut.comp713.customerorders.model;

import org.json.JSONException;
import org.json.JSONObject;

/** A customer account, as returned by POST /customer-login. */
public final class Customer {

    public final int id;
    public final String name;
    public final String email;

    private Customer(int id, String name, String email) {
        this.id = id;
        this.name = name;
        this.email = email;
    }

    public static Customer fromJson(JSONObject json) throws JSONException {
        return new Customer(
                json.getInt("id"),
                json.getString("name"),
                json.getString("email"));
    }
}
