-- db/init/002_seed.sql
-- 大量の仮データ生成（直近120日 / 約1000注文）

-- 乱数を少し安定させたい場合（毎回同じとは限らないが偏りは減る）
SELECT setseed(0.42);

-- customers: 250人（姓×名の組み合わせを重複なしで選ぶ）
WITH first_names AS (
  SELECT unnest(ARRAY[
    '太郎','花子','次郎','三郎','美咲','優子','健','玲奈','未来','翔','大輔','麻衣','蓮','陽菜','結衣',
    '悠真','陽斗','湊','蒼','樹','颯太','一真','大和','悠','航','陸','律','朝陽','瑛太','悠人',
    '結菜','葵','凛','杏','紬','心春','優奈','美月','莉子','芽依','陽葵','咲良','美優','彩乃','奈々',
    '直樹','拓海','亮','誠','悠斗','智也','裕也','祐介','直人','慎太郎','健太','剛','健一','浩二','和也'
  ]) AS fn
),
last_names AS (
  SELECT unnest(ARRAY[
    '佐藤','鈴木','高橋','田中','伊藤','渡辺','山本','中村','小林','加藤','吉田','山田','佐々木','山口','松本',
    '井上','木村','林','斎藤','清水','山崎','池田','阿部','橋本','石川','山下','森','前田','藤田','後藤',
    '岡田','長谷川','村上','近藤','石井','坂本','遠藤','青木','藤井','西村','福田','太田','三浦','藤原','岡本',
    '松田','中川','中島','原田','小川','竹内','金子','田村','和田','石田','上田','森田','柴田','原','宮崎',
    '酒井','工藤','横山','宮本','内田','高木','安藤','谷口','大野','丸山','今井','河野','高田','杉山','村田'
  ]) AS ln
),
pairs AS (
  -- ここで「姓×名」の全組み合わせを作る（重複なしの母集団）
  SELECT ln || ' ' || fn AS base_name
  FROM last_names CROSS JOIN first_names
),
picked AS (
  -- その中から 250 件をランダムに “重複なし” で選ぶ
  SELECT base_name
  FROM pairs
  ORDER BY random()
  LIMIT 250
)
INSERT INTO customers(name, email, created_at)
SELECT
  base_name || ' #' || lpad(row_number() OVER (ORDER BY base_name)::text, 4, '0') AS name,
  'user' || (row_number() OVER (ORDER BY base_name))::text || '@example.com' AS email,
  NOW() - (random()*200||' days')::interval AS created_at
FROM picked;

-- products: 40商品（カテゴリあり、価格レンジあり）
WITH cats AS (
  SELECT unnest(ARRAY['家電','食品','雑貨','文具','美容','スポーツ']) AS c
),
base AS (
  SELECT generate_series(1,40) AS i
)
INSERT INTO products(name, category, price_jpy, is_active)
SELECT
  CASE
    WHEN i <= 8  THEN '家電アイテム' || i
    WHEN i <= 16 THEN '食品アイテム' || i
    WHEN i <= 24 THEN '雑貨アイテム' || i
    WHEN i <= 32 THEN '文具アイテム' || i
    WHEN i <= 36 THEN '美容アイテム' || i
    ELSE              'スポーツアイテム' || i
  END,
  CASE
    WHEN i <= 8  THEN '家電'
    WHEN i <= 16 THEN '食品'
    WHEN i <= 24 THEN '雑貨'
    WHEN i <= 32 THEN '文具'
    WHEN i <= 36 THEN '美容'
    ELSE              'スポーツ'
  END,
  CASE
    WHEN i <= 8  THEN (5000 + (random()*30000)::int)     -- 家電: 5k〜35k
    WHEN i <= 16 THEN (300  + (random()*3000)::int)      -- 食品: 300〜3300
    WHEN i <= 24 THEN (800  + (random()*5000)::int)      -- 雑貨: 800〜5800
    WHEN i <= 32 THEN (100  + (random()*1500)::int)      -- 文具: 100〜1600
    WHEN i <= 36 THEN (900  + (random()*8000)::int)      -- 美容: 900〜8900
    ELSE              (1200 + (random()*12000)::int)     -- スポーツ: 1200〜13200
  END,
  CASE WHEN random() < 0.90 THEN TRUE ELSE FALSE END     -- 10%は非アクティブ
FROM base;

-- orders: 直近120日、合計1000注文
-- status は paid/shipped/cancelled/placed を混ぜる（キャンセル率が出る）
WITH ord AS (
  SELECT
    gs AS n,
    (CURRENT_DATE - ((random()*119)::int)) AS order_date,
    (1 + (random()*249)::int) AS customer_id,
    CASE
      WHEN random() < 0.60 THEN 'paid'
      WHEN random() < 0.80 THEN 'shipped'
      WHEN random() < 0.92 THEN 'placed'
      ELSE 'cancelled'
    END AS status
  FROM generate_series(1, 1000) gs
)
INSERT INTO orders(customer_id, status, order_date, total_jpy)
SELECT
  customer_id,
  status,
  order_date,
  0 -- 後で items から更新する
FROM ord;

-- order_items: 各注文に1〜4明細、商品はランダム
INSERT INTO order_items(order_id, product_id, quantity, unit_price_jpy)
SELECT
  o.order_id,
  (1 + (random()*39)::int) AS product_id,
  (1 + (random()*3)::int)  AS quantity,
  p.price_jpy               AS unit_price_jpy
FROM orders o
JOIN LATERAL generate_series(1, (1 + (random()*3)::int)) g(x) ON TRUE
JOIN products p ON p.product_id = (1 + (random()*39)::int);

-- orders.total_jpy を items 合計で更新（cancelledは0にする）
UPDATE orders o
SET total_jpy = CASE
  WHEN o.status = 'cancelled' THEN 0
  ELSE COALESCE(s.sum_jpy, 0)
END
FROM (
  SELECT oi.order_id, SUM(oi.unit_price_jpy * oi.quantity)::int AS sum_jpy
  FROM order_items oi
  GROUP BY oi.order_id
) s
WHERE o.order_id = s.order_id;

-- たまに端数を足して“現実っぽく”（任意）
UPDATE orders
SET total_jpy = total_jpy + (random()*200)::int
WHERE status IN ('paid','shipped') AND random() < 0.30;