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

//http + json helper using only java.net and org.json, the android platform apis
//every call blocks, so it must be run off the UI thread
public final class ApiClient {

    //10.0.2.2 is the emulator's address for the computer running the API
    //on a real phone change this to the computer's LAN address
    public static String BASE_URL = "http://10.0.2.2:8000";

    private static final int CONNECT_TIMEOUT_MS = 5000;
    private static final int READ_TIMEOUT_MS = 8000;

    //one shared pool for all network work
    //it is not shut down in onDestroy because rotation would then kill requests in flight
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

    //the pool all network work runs on
    public static ExecutorService executor() {
        return IO;
    }

    //get a resource and return the response body
    public static String get(String path) throws IOException, ApiException {
        return request("GET", path, null);
    }

    //post a json body and return the response body
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
