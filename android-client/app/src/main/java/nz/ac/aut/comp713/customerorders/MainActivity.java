package nz.ac.aut.comp713.customerorders;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;

import nz.ac.aut.comp713.customerorders.api.ApiClient;
import nz.ac.aut.comp713.customerorders.api.ApiException;
import nz.ac.aut.comp713.customerorders.model.Customer;

//screen 1: the customer signs in with their name and email
public class MainActivity extends Activity {

    private static final String STATE_NAME = "state_name";
    private static final String STATE_EMAIL = "state_email";
    private static final String STATE_STATUS = "state_status";

    private EditText nameInput;
    private EditText emailInput;
    private Button signInButton;
    private ProgressBar progress;
    private TextView statusView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_login);

        nameInput = findViewById(R.id.nameInput);
        emailInput = findViewById(R.id.emailInput);
        signInButton = findViewById(R.id.signInButton);
        progress = findViewById(R.id.progress);
        statusView = findViewById(R.id.statusView);

        //keep what was typed and any error message across rotation
        if (savedInstanceState != null) {
            nameInput.setText(savedInstanceState.getString(STATE_NAME, ""));
            emailInput.setText(savedInstanceState.getString(STATE_EMAIL, ""));
            statusView.setText(savedInstanceState.getString(STATE_STATUS, ""));
        }

        signInButton.setOnClickListener(v -> signIn());
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        outState.putString(STATE_NAME, nameInput.getText().toString());
        outState.putString(STATE_EMAIL, emailInput.getText().toString());
        outState.putString(STATE_STATUS, statusView.getText().toString());
    }

    private void signIn() {
        final String name = nameInput.getText().toString().trim();
        final String email = emailInput.getText().toString().trim();

        if (name.isEmpty() || email.isEmpty()) {
            statusView.setText(R.string.login_missing_details);
            return;
        }

        setLoading(true);

        //network calls must not run on the UI thread
        ApiClient.executor().execute(() -> {
            try {
                JSONObject request = new JSONObject();
                request.put("name", name);
                request.put("email", email);

                String body = ApiClient.post("/customer-login", request.toString());
                final Customer customer = Customer.fromJson(new JSONObject(body));

                runOnUiThread(() -> {
                    if (isDestroyed()) {
                        return;
                    }
                    setLoading(false);
                    Intent intent = new Intent(MainActivity.this, OrderListActivity.class);
                    intent.putExtra(OrderListActivity.EXTRA_CUSTOMER_ID, customer.id);
                    intent.putExtra(OrderListActivity.EXTRA_CUSTOMER_NAME, customer.name);
                    startActivity(intent);
                    finish();
                });
            } catch (ApiException e) {
                //401 means the login details did not match an account
                final String message = e.getStatusCode() == 401
                        ? getString(R.string.login_unknown)
                        : e.getMessage();
                showFailure(message);
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
            statusView.setText(message);
        });
    }

    private void setLoading(boolean loading) {
        progress.setVisibility(loading ? View.VISIBLE : View.GONE);
        signInButton.setEnabled(!loading);
        nameInput.setEnabled(!loading);
        emailInput.setEnabled(!loading);
    }
}
