begin;

alter table stock_favorite_stocks
  add column if not exists display_num integer;

create index if not exists stock_favorite_stocks_display_idx
  on stock_favorite_stocks (display_num asc, code asc, exchange asc);

delete from stock_favorite_stocks;

insert into stock_favorite_stocks (display_num, code, exchange, created_at, updated_at)
values
  (1, '000669', 'sz', now(), now()),
  (2, '300237', 'sz', now(), now()),
  (3, '300213', 'sz', now(), now()),
  (4, '300198', 'sz', now(), now()),
  (5, '300159', 'sz', now(), now()),
  (6, '300091', 'sz', now(), now()),
  (7, '002247', 'sz', now(), now()),
  (8, '603825', 'sh', now(), now()),
  (9, '600633', 'sh', now(), now()),
  (10, '600602', 'sh', now(), now()),
  (11, '002193', 'sz', now(), now()),
  (12, '300640', 'sz', now(), now()),
  (13, '001229', 'sz', now(), now()),
  (14, '002175', 'sz', now(), now()),
  (15, '300292', 'sz', now(), now()),
  (16, '300173', 'sz', now(), now()),
  (17, '000530', 'sz', now(), now()),
  (18, '600979', 'sh', now(), now()),
  (19, '002366', 'sz', now(), now()),
  (20, '000021', 'sz', now(), now()),
  (21, '300099', 'sz', now(), now()),
  (22, '300448', 'sz', now(), now()),
  (23, '002305', 'sz', now(), now()),
  (24, '002495', 'sz', now(), now()),
  (25, '300148', 'sz', now(), now()),
  (26, '300152', 'sz', now(), now()),
  (27, '300477', 'sz', now(), now()),
  (28, '002713', 'sz', now(), now()),
  (29, '002570', 'sz', now(), now()),
  (30, '300541', 'sz', now(), now()),
  (31, '300040', 'sz', now(), now()),
  (32, '300302', 'sz', now(), now()),
  (33, '600489', 'sh', now(), now()),
  (34, '300228', 'sz', now(), now()),
  (35, '603280', 'sh', now(), now()),
  (36, '300350', 'sz', now(), now()),
  (37, '603173', 'sh', now(), now()),
  (38, '603207', 'sh', now(), now()),
  (39, '603120', 'sh', now(), now()),
  (40, '002264', 'sz', now(), now()),
  (41, '600850', 'sh', now(), now()),
  (42, '002015', 'sz', now(), now()),
  (43, '301560', 'sz', now(), now()),
  (44, '301310', 'sz', now(), now()),
  (45, '603409', 'sh', now(), now()),
  (46, '300349', 'sz', now(), now()),
  (47, '600120', 'sh', now(), now()),
  (48, '002698', 'sz', now(), now()),
  (49, '300768', 'sz', now(), now()),
  (50, '301595', 'sz', now(), now()),
  (51, '301584', 'sz', now(), now()),
  (52, '300125', 'sz', now(), now()),
  (53, '002306', 'sz', now(), now()),
  (54, '603376', 'sh', now(), now()),
  (55, '600537', 'sh', now(), now()),
  (56, '300383', 'sz', now(), now()),
  (57, '002197', 'sz', now(), now()),
  (58, '002730', 'sz', now(), now()),
  (59, '603296', 'sh', now(), now()),
  (60, '000889', 'sz', now(), now()),
  (61, '300326', 'sz', now(), now()),
  (62, '300419', 'sz', now(), now());

commit;
