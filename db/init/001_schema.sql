-- db/init/001_schema.sql
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
  customer_id   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE products (
  product_id    INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name          TEXT NOT NULL,
  category      TEXT NOT NULL,
  price_jpy     INT NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE orders (
  order_id      INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id   INT NOT NULL REFERENCES customers(customer_id),
  status        TEXT NOT NULL CHECK (status IN ('paid','shipped','cancelled','placed')),
  order_date    DATE NOT NULL,
  total_jpy     INT NOT NULL
);

CREATE TABLE order_items (
  order_item_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id      INT NOT NULL REFERENCES orders(order_id),
  product_id    INT NOT NULL REFERENCES products(product_id),
  quantity      INT NOT NULL CHECK (quantity > 0),
  unit_price_jpy INT NOT NULL CHECK (unit_price_jpy >= 0)
);

CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);
CREATE INDEX idx_products_category ON products(category);