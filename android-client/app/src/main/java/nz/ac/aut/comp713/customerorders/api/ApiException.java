package nz.ac.aut.comp713.customerorders.api;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

//an error response from the api, keeps the status code and the server's message
public class ApiException extends Exception {

    private final int statusCode;

    public ApiException(int statusCode, String responseBody) {
        super(extractMessage(responseBody, statusCode));
        this.statusCode = statusCode;
    }

    public int getStatusCode() {
        return statusCode;
    }

    //fastapi sends {"detail": "..."} or {"detail": [{"msg": "..."}]} for validation errors
    private static String extractMessage(String body, int statusCode) {
        if (body == null || body.trim().isEmpty()) {
            return "The server returned an error (HTTP " + statusCode + ").";
        }
        try {
            JSONObject json = new JSONObject(body);
            Object detail = json.opt("detail");

            if (detail instanceof String) {
                return (String) detail;
            }

            if (detail instanceof JSONArray) {
                JSONArray items = (JSONArray) detail;
                StringBuilder message = new StringBuilder();
                for (int i = 0; i < items.length(); i++) {
                    if (i > 0) {
                        message.append(' ');
                    }
                    JSONObject item = items.optJSONObject(i);
                    message.append(item == null
                            ? items.optString(i, "invalid value")
                            : item.optString("msg", "invalid value"));
                }
                if (message.length() > 0) {
                    return message.toString();
                }
            }
        } catch (JSONException ignored) {
            // Not JSON after all; fall through to the generic message.
        }

        return "The server returned an error (HTTP " + statusCode + ").";
    }
}
