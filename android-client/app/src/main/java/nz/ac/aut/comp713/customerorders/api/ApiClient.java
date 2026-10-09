package nz.ac.aut.comp713.customerorders.api;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;

/**
 * Thin HTTP + JSON helper built only on java.net and org.json, which are
 * Android platform APIs (Week 9: HttpsURLConnection-style networking with no
 * third party client library).
 *
 * Every call here blocks on the network, so it must be run from a background
 * executor. Results are posted back to the UI thread by the caller with
 * Activity.runOnUiThread(...).
 *
 * The client never reads or writes the database directly: all data reaches the
 * app through the REST API, exactly as the assignment requires.
 */
public final class ApiClient {

    /**
     * 10.0.2.2 is the Android emulator's alias for the development machine's
     * own localhost, so the app reaches a backend running on the host at
     * port 8000. On a physical device, change this to the host machine's LAN
     * address (for example http://192.168.1.20:8000).
     */
    public static String BASE_URL = "http://10.0.2.2:8000";

    private static final int CONNECT_TIMEOUT_MS = 5000;
    private static final int READ_TIMEOUT_MS = 8000;

    /**
     * One shared, application scoped pool. It is deliberately NOT shut down in
     * Activity.onDestroy(): an Activity is destroyed and recreated on every
     * rotation, and killing the pool there would abandon an in-flight request
     * and lose the user's work. The callbacks check Activity.isDestroyed()
     * before touching any view instead.
     */
    private static final ExecutorService IO = Executors.newFixedThreadPool(2, new ThreadFactory() {
        @Override
        public Thread newThread(Runnable runnable) {
            Thread thread = new Thread(runnable, "customer-orders-io");
            thread.setDaemon(true);
            return thread;
        }
    });

    private ApiClient() {
    }

    /** The shared background pool that all network work must use. */
    public static ExecutorService executor() {
        return IO;
    }

    /** GET a resource and return the raw response body. */
    public static String get(String path) throws IOException, ApiException {
        return request("GET", path, null);
    }

    /** POST a JSON body and return the raw response body. */
    public static String post(String path, String jsonBody) throws IOException, ApiException {
        return request("POST", path, jsonBody);
    }

    private static String request(String method, String path, String jsonBody)
            throws IOException, ApiException {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(BASE_URL + path);
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod(method);
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setRequestProperty("Accept", "application/json");

            if (jsonBody != null) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                byte[] payload = jsonBody.getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(payload.length);
                OutputStream out = connection.getOutputStream();
                try {
                    out.write(payload);
                } finally {
                    out.close();
                }
            }

            int status = connection.getResponseCode();
            // On an error status the body is on getErrorStream(), not getInputStream().
            InputStream stream = status >= 400
                    ? connection.getErrorStream()
                    : connection.getInputStream();
            String body = readAll(stream);

            if (status >= 400) {
                throw new ApiException(status, body);
            }
            return body;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static String readAll(InputStream stream) throws IOException {
        if (stream == null) {
            return "";
        }
        BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8));
        try {
            StringBuilder body = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                body.append(line);
            }
            return body.toString();
        } finally {
            reader.close();
        }
    }
}
