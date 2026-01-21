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

-- db/init/003_seed_more.sql
-- 追加の仮データ（時系列・カテゴリ・TopN・キャンセル率・未注文顧客が出せるようにする）

-- customers (追加)
INSERT INTO customers (customer_id, name, email, created_at) VALUES
  (5,  '伊藤 恒一',   'ito@example.com',   '2025-11-10 09:00:00'),
  (6,  '山本 未来',   'yamamoto@example.com','2025-11-18 09:00:00'),
  (7,  '中村 玲奈',   'nakamura@example.com','2025-12-02 09:00:00'),
  (8,  '小林 健',     'kobayashi@example.com','2025-12-10 09:00:00'),
  (9,  '加藤 優子',   'kato@example.com',  '2025-12-20 09:00:00'),
  (10, '吉田 翔',     'yoshida@example.com','2025-12-25 09:00:00'),
  (11, '松本 美咲',   'matsumoto@example.com','2026-01-05 09:00:00'),
  (12, '森 大輔',     'mori@example.com',  '2026-01-10 09:00:00')
ON CONFLICT (customer_id) DO NOTHING;

-- products (追加)
INSERT INTO products (product_id, name, category, price_jpy, is_active) VALUES
  (9,  'コーヒー豆I',      '食品', 1200, TRUE),
  (10, '電気ケトルJ',      '家電', 6400, TRUE),
  (11, 'マウスK',          '家電', 3200, TRUE),
  (12, 'ボールペンL',      '文具', 180,  TRUE),
  (13, 'お茶M',            '食品', 600,  TRUE),
  (14, '収納ボックスN',    '雑貨', 2000, TRUE),
  (15, 'ノートPCスタンドO','家電', 3800, TRUE),
  (16, '販売終了P',        '家電', 9999, FALSE)
ON CONFLICT (product_id) DO NOTHING;

-- orders (追加) : paid/shipped/cancelled を混ぜ、日別売上・直近N日集計が出るように散らす
-- ここでは total_jpy を “売上” として使えるよう、items合計と近い値にしています（完全一致でなくてもOK）
INSERT INTO orders (order_id, customer_id, status, order_date, total_jpy) VALUES
  (101, 5,  'paid',      '2025-11-20',  2400),
  (102, 6,  'paid',      '2025-11-25',  6400),
  (103, 7,  'cancelled', '2025-11-28',     0),
  (104, 8,  'shipped',   '2025-12-02',  5200),
  (105, 5,  'paid',      '2025-12-05',  1800),
  (106, 9,  'paid',      '2025-12-08',  2000),
  (107, 10, 'paid',      '2025-12-10',  1200),
  (108, 6,  'paid',      '2025-12-12',  9600),
  (109, 7,  'cancelled', '2025-12-15',     0),
  (110, 8,  'paid',      '2025-12-18',  3800),
  (111, 9,  'shipped',   '2025-12-20',  6400),
  (112, 10, 'paid',      '2025-12-22',  4200),
  (113, 11, 'paid',      '2025-12-26',  3000),
  (114, 12, 'paid',      '2025-12-28',  8600),
  (115, 5,  'paid',      '2026-01-03',  2400),
  (116, 6,  'paid',      '2026-01-05', 12800),
  (117, 7,  'paid',      '2026-01-07',  2000),
  (118, 8,  'cancelled', '2026-01-08',     0),
  (119, 9,  'paid',      '2026-01-10',  3200),
  (120, 10, 'shipped',   '2026-01-12',  3800),
  (121, 11, 'paid',      '2026-01-13',  1800),
  (122, 12, 'paid',      '2026-01-14',  7000),
  (123, 6,  'paid',      '2026-01-15',  1200)
ON CONFLICT (order_id) DO NOTHING;

-- order_items (追加)
-- ※ order_items に主キー列がある/ないで書き方が変わります。
-- ここでは「(order_id, product_id, quantity, unit_price_jpy) が存在する」想定で書いています。
-- もし order_item_id が必須なら、このINSERTに order_item_id を追加してください。

INSERT INTO order_items (order_id, product_id, quantity, unit_price_jpy) VALUES
  (101,  9, 2, 1200),     -- コーヒー豆I
  (102, 10, 1, 6400),     -- 電気ケトルJ
  (103, 11, 1, 3200),     -- cancelled (本来は0にしてもOK)
  (104, 14, 2, 2000),     -- 収納ボックスN
  (104, 12, 3,  180),     -- ボールペンL
  (105, 12, 10, 180),     -- 文具まとめ買い
  (106, 14, 1, 2000),
  (107, 13, 2,  600),     -- お茶M
  (108, 10, 1, 6400),
  (108, 11, 1, 3200),
  (109, 15, 1, 3800),     -- cancelled
  (110, 15, 1, 3800),
  (111, 10, 1, 6400),     -- shipped
  (112,  9, 1, 1200),
  (112, 14, 1, 2000),
  (112, 12, 5,  180),
  (113, 14, 1, 2000),
  (113, 12, 5,  180),
  (114, 10, 1, 6400),
  (114, 15, 1, 3800),
  (115,  9, 2, 1200),
  (116, 11, 4, 3200),     -- 12800（高単価トップが出やすい）
  (117, 14, 1, 2000),
  (118, 12, 2,  180),     -- cancelled
  (119, 11, 1, 3200),
  (120, 15, 1, 3800),     -- shipped
  (121, 12, 10, 180),
  (122, 10, 1, 6400),
  (122,  9, 1, 1200),
  (123, 13, 2,  600)
;