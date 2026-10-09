package nz.ac.aut.comp713.customerorders;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import nz.ac.aut.comp713.customerorders.api.ApiClient;
import nz.ac.aut.comp713.customerorders.api.ApiException;
import nz.ac.aut.comp713.customerorders.model.Order;
import nz.ac.aut.comp713.customerorders.model.Product;

//screen 2: the signed in customer sees their orders and their current status
//staff change the status on the web client and it shows up here
public class OrderListActivity extends Activity {

    public static final String EXTRA_CUSTOMER_ID = "extra_customer_id";
    public static final String EXTRA_CUSTOMER_NAME = "extra_customer_name";

    private int customerId;
    private String customerName;

    private TextView welcomeView;
    private TextView signedInAsView;
    private ProgressBar progress;
    private TextView statusView;
    private Button retryButton;
    private TextView emptyView;
    private ListView orderList;
    private Button refreshButton;
    private Button newOrderButton;

    private final List<Order> orders = new ArrayList<>();
    private final Map<Integer, String> productNames = new HashMap<>();
    private OrderAdapter adapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_order_list);

        customerId = getIntent().getIntExtra(EXTRA_CUSTOMER_ID, -1);
        customerName = getIntent().getStringExtra(EXTRA_CUSTOMER_NAME);

        welcomeView = findViewById(R.id.welcomeView);
        signedInAsView = findViewById(R.id.signedInAsView);
        progress = findViewById(R.id.progress);
        statusView = findViewById(R.id.statusView);
        retryButton = findViewById(R.id.retryButton);
        emptyView = findViewById(R.id.emptyView);
        orderList = findViewById(R.id.orderList);
        refreshButton = findViewById(R.id.refreshButton);
        newOrderButton = findViewById(R.id.newOrderButton);

        signedInAsView.setText(getString(R.string.orders_signed_in_as,
                customerName == null ? "" : customerName));

        adapter = new OrderAdapter();
        orderList.setAdapter(adapter);

        retryButton.setOnClickListener(v -> loadOrders());
        refreshButton.setOnClickListener(v -> loadOrders());
        newOrderButton.setOnClickListener(v -> {
            Intent intent = new Intent(OrderListActivity.this, CreateOrderActivity.class);
            intent.putExtra(CreateOrderActivity.EXTRA_CUSTOMER_ID, customerId);
            startActivity(intent);
        });

        //load orders in onResume so they refresh when coming back to this screen
    }

    @Override
    protected void onResume() {
        super.onResume();
        loadOrders();
    }

    private void loadOrders() {
        if (customerId < 0) {
            showFailure(getString(R.string.error_unexpected));
            return;
        }

        setLoading(true);

        ApiClient.executor().execute(() -> {
            try {
                //products are fetched too so orders can show a name instead of just an id
                String productsBody = ApiClient.get("/products");
                String ordersBody = ApiClient.get("/customers/" + customerId + "/orders");

                final Map<Integer, String> names = new HashMap<>();
                JSONArray productsJson = new JSONArray(productsBody);
                for (int i = 0; i < productsJson.length(); i++) {
                    Product product = Product.fromJson(productsJson.getJSONObject(i));
                    names.put(product.id, product.name);
                }

                final List<Order> loaded = new ArrayList<>();
                JSONArray ordersJson = new JSONArray(ordersBody);
                for (int i = 0; i < ordersJson.length(); i++) {
                    loaded.add(Order.fromJson(ordersJson.getJSONObject(i)));
                }

                runOnUiThread(() -> {
                    if (isDestroyed()) {
                        return;
                    }
                    productNames.clear();
                    productNames.putAll(names);
                    orders.clear();
                    orders.addAll(loaded);
                    setLoading(false);
                    render();
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

    private void render() {
        boolean empty = orders.isEmpty();
        emptyView.setVisibility(empty ? View.VISIBLE : View.GONE);
        orderList.setVisibility(empty ? View.GONE : View.VISIBLE);
        adapter.notifyDataSetChanged();
    }

    private void showFailure(final String message) {
        runOnUiThread(() -> {
            if (isDestroyed()) {
                return;
            }
            setLoading(false);
            statusView.setText(message);
            statusView.setVisibility(View.VISIBLE);
            retryButton.setVisibility(View.VISIBLE);
        });
    }

    private void setLoading(boolean loading) {
        progress.setVisibility(loading ? View.VISIBLE : View.GONE);
        refreshButton.setEnabled(!loading);
        newOrderButton.setEnabled(!loading);
        if (loading) {
            statusView.setVisibility(View.GONE);
            retryButton.setVisibility(View.GONE);
        }
    }

    private String describeDelivery(Order order) {
        String destination;
        if (order.hasDeviceLocation()) {
            destination = String.format(Locale.US, "device location (%.5f, %.5f)",
                    order.latitude, order.longitude);
        } else if (order.deliveryAddress != null && !order.deliveryAddress.isEmpty()) {
            destination = order.deliveryAddress;
        } else {
            destination = "no delivery details";
        }
        return "Status: " + order.status + "\nDeliver to: " + destination;
    }

    //shows one row per order
    private final class OrderAdapter extends BaseAdapter {

        @Override
        public int getCount() {
            return orders.size();
        }

        @Override
        public Object getItem(int position) {
            return orders.get(position);
        }

        @Override
        public long getItemId(int position) {
            return orders.get(position).id;
        }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            View row = convertView;
            if (row == null) {
                row = LayoutInflater.from(OrderListActivity.this)
                        .inflate(R.layout.list_item_order, parent, false);
            }

            Order order = orders.get(position);
            TextView title = row.findViewById(R.id.orderTitle);
            TextView detail = row.findViewById(R.id.orderDetail);

            String productName = productNames.containsKey(order.productId)
                    ? productNames.get(order.productId)
                    : "product #" + order.productId;

            title.setText(String.format(Locale.US, "Order #%d - %s x %d",
                    order.id, productName, order.quantity));
            detail.setText(describeDelivery(order));
            return row;
        }
    }
}
