INSERT INTO customers (name, email, created_at) VALUES
('田中 太郎', 'tanaka@example.com', NOW() - INTERVAL '120 days'),
('佐藤 花子', 'sato@example.com',   NOW() - INTERVAL '60 days'),
('鈴木 次郎', 'suzuki@example.com', NOW() - INTERVAL '10 days');

INSERT INTO products (name, category, price_jpy, is_active) VALUES
('加湿器A', '家電', 9800, TRUE),
('イヤホンB', '家電', 12800, TRUE),
('プロテインC', '食品', 4200, TRUE),
('マグカップD', '雑貨', 1500, TRUE),
('旧モデルE', '家電', 5000, FALSE);

-- orders（適当に日付をばらす）
INSERT INTO orders (customer_id, order_date, status, total_jpy) VALUES
(1, CURRENT_DATE - 30, 'paid',  22600),
(1, CURRENT_DATE - 5,  'shipped', 1500),
(2, CURRENT_DATE - 7,  'cancelled', 4200),
(3, CURRENT_DATE - 2,  'paid',  12800);

INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy) VALUES
(1, 1, 1, 9800),
(1, 2, 1, 12800),
(2, 4, 1, 1500),
(3, 3, 1, 4200),
(4, 2, 1, 12800);