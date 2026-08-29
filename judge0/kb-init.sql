-- Judge0 PostgreSQL 首次初始化脚本：为知识库创建独立用户与数据库
-- 仅在数据卷首次初始化时执行
CREATE ROLE interview LOGIN PASSWORD 'kb_pass_2025_dev';
CREATE DATABASE interview_kb OWNER interview;
