package nz.ac.aut.comp713.customerorders.api;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * A non-2xx response from the REST API. Carries the HTTP status code plus a
 * human readable message taken from the server's error body, so the screen can
 * show the difference between "no such customer" and "the server is down".
 */
public class ApiException extends Exception {

    private final int statusCode;

    public ApiException(int statusCode, String responseBody) {
        super(extractMessage(responseBody, statusCode));
        this.statusCode = statusCode;
    }

    public int getStatusCode() {
        return statusCode;
    }

    /**
     * FastAPI returns {"detail": "..."} for most errors, and
     * {"detail": [{"msg": "...", ...}]} for request validation errors.
     * Both shapes are unwrapped so the user sees the real reason.
     */
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
