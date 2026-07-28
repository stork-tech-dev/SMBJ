-- ============================================================================
-- SEED INICIAL — Soleil / Mallorca
-- ============================================================================
-- Se ejecuta DESPUÉS de `alembic upgrade head`.
--
-- El script es idempotente: correrlo dos veces no duplica nada.
--
-- Los bloques que dependen de tablas del módulo 02 (roles, usuarios) están
-- protegidos con `to_regclass`: si esas tablas todavía no existen, el
-- bloque se saltea con un aviso. Volver a correr este mismo archivo
-- después de aplicar las migraciones del módulo 02 crea la Cuenta Maestra.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. Configuración del sistema (fila única)
-- ----------------------------------------------------------------------------
INSERT INTO configuracion_sistema
    (redondeo, descuento_maximo, metodo_descuento, letra_empresa, updated_at, updated_by)
SELECT 10.00, 30.00, 'encadenado', 'S', NOW(), NULL
WHERE NOT EXISTS (SELECT 1 FROM configuracion_sistema);


-- ----------------------------------------------------------------------------
-- 2. Motivos de baja de stock
-- ----------------------------------------------------------------------------
INSERT INTO motivos_baja (nombre, activo)
VALUES
    ('Rotura',  TRUE),
    ('Robo',    TRUE),
    ('Muestra', TRUE),
    ('Merma',   TRUE)
ON CONFLICT (nombre) DO NOTHING;


-- ----------------------------------------------------------------------------
-- 3. Roles del sistema (módulo 02)
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regclass('public.roles') IS NULL THEN
        RAISE NOTICE 'Tabla roles inexistente todavía: se saltea la carga de roles. '
                     'Volver a correr seed.sql después de las migraciones del módulo 02.';
        RETURN;
    END IF;

    INSERT INTO roles (nombre, descripcion, es_sistema, activo, created_at, updated_at)
    VALUES
        ('cuenta_maestra', 'Acceso total al sistema',                    TRUE, TRUE, NOW(), NOW()),
        ('dueno',          'Dueño: gestión completa del negocio',        TRUE, TRUE, NOW(), NOW()),
        ('supervisor',     'Supervisa vendedores y operación diaria',    TRUE, TRUE, NOW(), NOW()),
        ('vendedor',       'Operación de punto de venta',                TRUE, TRUE, NOW(), NOW()),
        ('distribucion',   'Depósito, remitos y transferencias',         TRUE, TRUE, NOW(), NOW()),
        ('auditor',        'Solo lectura de auditoría y reportes',       TRUE, TRUE, NOW(), NOW())
    ON CONFLICT (nombre) DO NOTHING;
END;
$$;


-- ----------------------------------------------------------------------------
-- 4. Usuario Cuenta Maestra (módulo 02)
-- ----------------------------------------------------------------------------
-- Usuario:    admin
-- Contraseña: Admin1234!   (bcrypt, cost 12)
--
-- El cambio obligatorio en el primer login se detecta por
-- `ultimo_acceso IS NULL`: mientras siga en NULL, el login redirige a la
-- pantalla de cambio de contraseña. Solo se marca al completar el cambio.
--
-- CAMBIAR ESTA CONTRASEÑA ANTES DE PONER EL SISTEMA EN PRODUCCIÓN.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_rol_id BIGINT;
BEGIN
    IF to_regclass('public.usuarios') IS NULL THEN
        RAISE NOTICE 'Tabla usuarios inexistente todavía: se saltea la Cuenta Maestra. '
                     'Volver a correr seed.sql después de las migraciones del módulo 02.';
        RETURN;
    END IF;

    SELECT id INTO v_rol_id FROM roles WHERE nombre = 'cuenta_maestra';

    INSERT INTO usuarios
        (username, email, password_hash, nombre, rol_id, activo,
         clave_especial_hash, created_at, updated_at, ultimo_acceso)
    SELECT
        'admin',
        NULL,
        '$2b$12$vqnJys9FDtGASzhHslS2QezvhXmIq5EVGtws/4GqN65si5A/jF4r.',
        'Cuenta Maestra',
        v_rol_id,
        TRUE,
        NULL,
        NOW(),
        NOW(),
        NULL
    WHERE NOT EXISTS (SELECT 1 FROM usuarios WHERE username = 'admin');
END;
$$;


-- ----------------------------------------------------------------------------
-- 4b. Permisos base de los roles del sistema (módulo 02)
-- ----------------------------------------------------------------------------
-- Una fila por (rol, módulo) con recurso=NULL = permiso general del módulo,
-- más filas puntuales por recurso donde hace falta acceso granular.
--
-- La Cuenta Maestra igual tiene acceso total resuelto en código
-- (`resolver_permiso`), pero se le cargan las filas para que el árbol de
-- permisos de la UI muestre la realidad y no todo en falso.
--
-- Los módulos que no aparecen para un rol quedan sin fila = sin acceso.
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regclass('public.rol_permisos') IS NULL THEN
        RAISE NOTICE 'Tabla rol_permisos inexistente todavía: se saltean los permisos. '
                     'Volver a correr seed.sql después de las migraciones del módulo 02.';
        RETURN;
    END IF;

    -- Permisos generales por módulo (recurso = NULL).
    INSERT INTO rol_permisos (rol_id, modulo, recurso, puede_ver, puede_crear, puede_editar, puede_eliminar)
    SELECT r.id, p.modulo, NULL, p.ver, p.crear, p.editar, p.eliminar
    FROM (VALUES
        -- rol,             módulo,           ver,   crear, editar, eliminar
        ('cuenta_maestra', 'clientes',        TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'proveedores',     TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'productos',       TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'compras',         TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'ventas',          TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'facturacion',     TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'tesoreria',       TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'reportes',        TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'configuracion',   TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'auditoria',       TRUE,  FALSE, FALSE, FALSE),
        ('cuenta_maestra', 'usuarios',        TRUE,  TRUE,  TRUE,  TRUE),
        ('cuenta_maestra', 'dispositivos',    TRUE,  TRUE,  TRUE,  TRUE),

        ('dueno',          'clientes',        TRUE,  TRUE,  TRUE,  TRUE),
        ('dueno',          'proveedores',     TRUE,  TRUE,  TRUE,  TRUE),
        ('dueno',          'productos',       TRUE,  TRUE,  TRUE,  TRUE),
        ('dueno',          'compras',         TRUE,  TRUE,  TRUE,  TRUE),
        ('dueno',          'ventas',          TRUE,  TRUE,  TRUE,  TRUE),
        ('dueno',          'facturacion',     TRUE,  TRUE,  TRUE,  TRUE),
        ('dueno',          'tesoreria',       TRUE,  TRUE,  TRUE,  TRUE),
        ('dueno',          'reportes',        TRUE,  FALSE, FALSE, FALSE),
        -- crear habilitado: el Dueño da de alta puntos de venta (sesión 03b).
        ('dueno',          'configuracion',   TRUE,  TRUE,  TRUE,  FALSE),
        ('dueno',          'auditoria',       FALSE, FALSE, FALSE, FALSE),
        ('dueno',          'usuarios',        TRUE,  TRUE,  TRUE,  FALSE),
        ('dueno',          'dispositivos',    TRUE,  TRUE,  TRUE,  TRUE),

        ('supervisor',     'clientes',        TRUE,  TRUE,  TRUE,  FALSE),
        ('supervisor',     'proveedores',     TRUE,  FALSE, FALSE, FALSE),
        ('supervisor',     'productos',       TRUE,  FALSE, FALSE, FALSE),
        ('supervisor',     'ventas',          TRUE,  TRUE,  TRUE,  FALSE),
        ('supervisor',     'facturacion',     TRUE,  TRUE,  FALSE, FALSE),
        ('supervisor',     'tesoreria',       TRUE,  FALSE, FALSE, FALSE),
        ('supervisor',     'reportes',        FALSE, FALSE, FALSE, FALSE),
        ('supervisor',     'usuarios',        TRUE,  TRUE,  TRUE,  FALSE),
        ('supervisor',     'dispositivos',    TRUE,  FALSE, FALSE, FALSE),

        ('vendedor',       'clientes',        TRUE,  TRUE,  FALSE, FALSE),
        ('vendedor',       'productos',       TRUE,  FALSE, FALSE, FALSE),
        ('vendedor',       'ventas',          TRUE,  TRUE,  FALSE, FALSE),
        ('vendedor',       'facturacion',     TRUE,  TRUE,  FALSE, FALSE),
        ('vendedor',       'reportes',        FALSE, FALSE, FALSE, FALSE),

        ('distribucion',   'productos',       TRUE,  FALSE, TRUE,  FALSE),
        -- Distribución hace el ABM de proveedores y cambia su dólar (sesión 03).
        ('distribucion',   'proveedores',     TRUE,  TRUE,  TRUE,  FALSE),
        ('distribucion',   'compras',         TRUE,  TRUE,  FALSE, FALSE),
        ('distribucion',   'dispositivos',    TRUE,  FALSE, FALSE, FALSE),

        ('auditor',        'auditoria',       TRUE,  FALSE, FALSE, FALSE),
        ('auditor',        'reportes',        TRUE,  FALSE, FALSE, FALSE),
        ('auditor',        'usuarios',        TRUE,  FALSE, FALSE, FALSE)
    ) AS p(rol, modulo, ver, crear, editar, eliminar)
    JOIN roles r ON r.nombre = p.rol
    ON CONFLICT (rol_id, modulo, recurso) DO NOTHING;

    -- Permisos por recurso específico.
    INSERT INTO rol_permisos (rol_id, modulo, recurso, puede_ver, puede_crear, puede_editar, puede_eliminar)
    SELECT r.id, p.modulo, p.recurso, p.ver, p.crear, p.editar, p.eliminar
    FROM (VALUES
        -- El supervisor no ve reportes en general, pero sí el de ventas diarias.
        ('supervisor',   'reportes',  'reporte.ventas_diarias', TRUE,  FALSE, FALSE, FALSE),
        ('supervisor',   'ventas',    'venta.descuento',        FALSE, TRUE,  FALSE, FALSE),
        ('supervisor',   'ventas',    'venta.anular',           FALSE, FALSE, FALSE, TRUE),
        ('supervisor',   'tesoreria', 'caja.arqueo',            FALSE, TRUE,  FALSE, FALSE),
        ('vendedor',     'ventas',    'venta.descuento',        FALSE, TRUE,  FALSE, FALSE),
        ('distribucion', 'productos', 'stock.baja',             FALSE, TRUE,  FALSE, FALSE),
        ('distribucion', 'productos', 'stock.auditoria',        FALSE, TRUE,  FALSE, FALSE)
    ) AS p(rol, modulo, recurso, ver, crear, editar, eliminar)
    JOIN roles r ON r.nombre = p.rol
    ON CONFLICT (rol_id, modulo, recurso) DO NOTHING;
END;
$$;


-- ----------------------------------------------------------------------------
-- 5. Registro de auditoría del seed
-- ----------------------------------------------------------------------------
-- usuario_id NULL = acción del sistema (Principio 3).
INSERT INTO auditoria (usuario_id, accion, entidad, entidad_id, estado_nuevo, ip_origen, timestamp)
SELECT
    NULL,
    'sistema.seed',
    'configuracion_sistema',
    NULL,
    jsonb_build_object('detalle', 'Carga de datos iniciales ejecutada'),
    NULL,
    NOW()
WHERE NOT EXISTS (SELECT 1 FROM auditoria WHERE accion = 'sistema.seed');
