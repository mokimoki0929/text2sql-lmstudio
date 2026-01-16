-- Add more customers (incl. no-order customer)
INSERT INTO customers (name, email, created_at) VALUES
('高橋 三郎', 'takahashi@example.com', NOW() - INTERVAL '20 days');

-- Add more products
INSERT INTO products (name, category, price_jpy, is_active) VALUES
('掃除機F', '家電', 22000, TRUE),
('クッキーG', '食品', 800, TRUE),
('ノートH', '文具', 300, TRUE);

-- Helper: create orders and items by product name (keeps IDs stable)
-- Order A: customer 2, paid, last month-ish (CURRENT_DATE - 40)
WITH o AS (
  INSERT INTO orders (customer_id, order_date, status, total_jpy)
  VALUES (2, CURRENT_DATE - 40, 'paid', 2300)
  RETURNING order_id
)
INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy)
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='マグカップD'
UNION ALL
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='クッキーG';

-- Order B: customer 1, paid, (CURRENT_DATE - 20), multiple quantity
WITH o AS (
  INSERT INTO orders (customer_id, order_date, status, total_jpy)
  VALUES (1, CURRENT_DATE - 20, 'paid', 3900)
  RETURNING order_id
)
INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy)
SELECT o.order_id, p.product_id, 3, p.price_jpy FROM o JOIN products p ON p.name='クッキーG'
UNION ALL
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='マグカップD';

-- Order C: customer 3, shipped, (CURRENT_DATE - 12)
WITH o AS (
  INSERT INTO orders (customer_id, order_date, status, total_jpy)
  VALUES (3, CURRENT_DATE - 12, 'shipped', 22000)
  RETURNING order_id
)
INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy)
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='掃除機F';

-- Order D: customer 2, cancelled, (CURRENT_DATE - 9)
WITH o AS (
  INSERT INTO orders (customer_id, order_date, status, total_jpy)
  VALUES (2, CURRENT_DATE - 9, 'cancelled', 9800)
  RETURNING order_id
)
INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy)
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='加湿器A';

-- Order E: customer 1, paid, current month (CURRENT_DATE - 3)
WITH o AS (
  INSERT INTO orders (customer_id, order_date, status, total_jpy)
  VALUES (1, CURRENT_DATE - 3, 'paid', 22300)
  RETURNING order_id
)
INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy)
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='掃除機F'
UNION ALL
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='ノートH';

-- Order F: customer 3, placed, (CURRENT_DATE - 1)
WITH o AS (
  INSERT INTO orders (customer_id, order_date, status, total_jpy)
  VALUES (3, CURRENT_DATE - 1, 'placed', 800)
  RETURNING order_id
)
INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy)
SELECT o.order_id, p.product_id, 1, p.price_jpy FROM o JOIN products p ON p.name='クッキーG';
