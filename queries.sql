-- Example SQL queries against lab.db (run: sqlite3 lab.db < queries.sql)

-- 1. Critical results still to be phoned through to the ward
SELECT p.patient_id, p.family_name, r.test_name, r.value, r.units, r.flag
FROM results r
JOIN orders o   ON o.id = r.order_id
JOIN patients p ON p.patient_id = o.patient_id
WHERE r.flag IN ('HH', 'LL', 'AA');

-- 2. Abnormal rate per test (data-quality and workload check)
SELECT test_name,
       COUNT(*)                                    AS total,
       SUM(flag <> 'N')                            AS abnormal,
       ROUND(100.0 * SUM(flag <> 'N') / COUNT(*), 1) AS pct_abnormal
FROM results
GROUP BY test_name
ORDER BY pct_abnormal DESC;

-- 3. Messages received per sending system (interface monitoring)
SELECT sending_app, sending_facility, COUNT(*) AS messages, MAX(received_at) AS last_received
FROM messages
GROUP BY sending_app, sending_facility;

-- 4. Where the flag came from: analyser, reference range, or critical limit
SELECT flag_source, flag, COUNT(*) AS n
FROM results
GROUP BY flag_source, flag
ORDER BY flag_source, flag;

-- 5. Full result history for one patient
SELECT o.observed_at, o.test_name AS panel, r.test_name, r.value, r.units, r.reference_range, r.flag
FROM results r
JOIN orders o ON o.id = r.order_id
WHERE o.patient_id = 'MRN100002'
ORDER BY o.observed_at, r.set_id;
