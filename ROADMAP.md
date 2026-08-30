# Roadmap de UI/UX

Este roadmap prioriza las mejoras que hacen PokeTokenBar para Windows más agradable, sencillo, bonito y funcional. No pretende reproducir toda la infraestructura interna del proyecto original de macOS.

## Criterios de alcance

Se priorizan cambios con un efecto visible en la experiencia del usuario:

- Claridad de la información.
- Facilidad de navegación.
- Calidad visual y consistencia.
- Feedback inmediato ante acciones.
- Personalización útil.
- Mejor integración con el escritorio de Windows.

Quedan fuera, salvo que resuelvan un problema visible en Windows:

- Crash reporters avanzados.
- Rotación y migración histórica de logs.
- Keychain y mecanismos exclusivos de macOS.
- Homebrew, LaunchAgent y otros componentes de distribución de macOS.
- Arneses internos sin impacto directo en la experiencia.
- Paridad completa con todos los proveedores del upstream.

## Prioridad alta: experiencia principal

### Pet flotante de escritorio

- [x] Mostrar el compañero fuera de la bandeja del sistema.
- [x] Permitir arrastrarlo y recordar su posición.
- [x] Permitir configurar su tamaño.
- [x] Abrir la ventana principal al hacer clic.
- [x] Mostrar el consumo al pasar el cursor.
- [x] Superponer al pasar el cursor el porcentaje hasta eclosión, evolución o graduación.
- [x] Ofrecer un menú contextual sencillo.
- [x] Permitir volver a mostrarlo directamente desde el menú contextual de la bandeja.
- [x] Mostrar alertas de límites mediante bocadillos.
- [x] Mantenerlo dentro de una pantalla válida al cambiar monitores o resolución.

### Sprites y animaciones

- [x] Animar el Pokémon actual con sprites Gen-V.
- [x] Animar el huevo mientras espera la eclosión.
- [x] Mantener un fallback estático cuando no exista animación.
- [x] Usar escalado pixel-perfect sin suavizado borroso.
- [x] Precargar sprites para evitar saltos o imágenes tardías.
- [x] Reducir o detener animaciones cuando no sean visibles.

### Pantalla Home

- [x] Dar protagonismo visual al Pokémon actual.
- [x] Mostrar claramente el progreso del huevo o estadio actual.
- [x] Mostrar evolución actual y siguiente.
- [x] Mostrar rareza, naturaleza y condición Shiny.
- [x] Crear un resumen compacto de consumo y límites.
- [x] Evitar grandes zonas vacías.
- [x] Adaptar correctamente nombres y cifras largas.
- [x] Ajustar dinámicamente la altura de proveedores para priorizar los límites oficiales.
- [x] Mantener el porcentaje de progreso legible fuera del relleno de la barra.

### Celebraciones y feedback

- [x] Añadir celebración de eclosión.
- [x] Añadir celebración de evolución.
- [x] Añadir celebración de graduación.
- [x] Añadir celebración especial para Shiny.
- [x] Mostrar feedback inmediato al usar Rare Candy.
- [x] Mostrar la nueva naturaleza al usar Mint.
- [x] Mantener las animaciones breves y no intrusivas.

### Pokémon representante

- [x] Permitir elegir cualquier especie poseída como representante.
- [x] Mostrar el representante en la bandeja y el pet flotante.
- [x] Mantener su selección independiente del compañero que se está criando.
- [x] Permitir volver al modo «seguir al compañero actual».

## Colección y progresión

### Pokédex

- [x] Presentar las especies en una cuadrícula ordenada por número.
- [x] Añadir paginación o navegación compacta.
- [x] Diferenciar visualmente especies normales y Shiny.
- [x] Permitir alternar el sprite normal/Shiny de una especie poseída.
- [x] Mostrar contadores totales y por rareza.
- [x] Diseñar estados vacíos cuidados.

### Registro de capturas

- [x] Separar el registro individual del Pokédex consolidado.
- [x] Ordenar capturas de más reciente a más antigua.
- [x] Mostrar línea evolutiva, rareza, naturaleza y fecha.
- [x] Identificar claramente capturas Shiny.

### Línea evolutiva visual

- [x] Diferenciar formas obtenidas, actual y futuras.
- [x] Representar ramas evolutivas sin saturar la pantalla.
- [x] Mostrar estados desconocidos con un tratamiento visual coherente.

## Navegación y claridad

- [x] Mantener cuatro áreas principales: Home, Collection, Bag y Shop.
- [x] Usar pestañas por proveedor solo cuando haya varios detectados.
- [x] Mantener el resumen combinado fácilmente accesible.
- [x] Añadir estados vacíos claros en colección, mochila y proveedores.
- [x] Diferenciar visualmente «actualizando», «actualizado», «obsoleto» y «error».
- [x] Evitar mostrar excepciones o mensajes técnicos crudos al usuario.
- [x] Hacer predecible el cierre y la reapertura desde la bandeja.
- [x] Añadir tooltips a las acciones poco evidentes.

## Bandeja del sistema

- [x] Ofrecer modo solo personaje.
- [x] Permitir mostrar u ocultar tokens de hoy.
- [x] Permitir mostrar u ocultar coste.
- [x] Permitir mostrar u ocultar porcentaje de límite.
- [x] Mantener un tooltip compacto con el estado esencial.
- [x] Garantizar buena legibilidad con escalado DPI y temas claro/oscuro.

## Límites y consumo

- [x] Mostrar límites mediante barras de progreso claras.
- [x] Mostrar cuenta atrás hasta el reinicio cuando esté disponible.
- [x] Permitir alternar porcentaje usado y restante.
- [x] Aplicar colores coherentes para estado normal, advertencia y crítico.
- [x] Permitir configurar los umbrales de advertencia y crítico.
- [x] Evitar notificaciones repetidas mientras se mantiene el mismo estado.
- [x] Añadir una previsión sencilla de agotamiento antes del reinicio.
- [x] Señalar datos obsoletos sin confundirlos con un fallo de la aplicación.
- [x] Mostrar Luna Reserve debajo de los límites Codex principales y antes de los créditos de reset.
- [x] Evitar Rare Candy duplicados cuando el timestamp de reset fluctúa unos segundos.

## Tienda y mochila

- [x] Diseñar tarjetas visuales para objetos y huevos.
- [x] Mostrar icono, nombre, efecto y precio de forma inmediata.
- [x] Mostrar saldo disponible de manera consistente.
- [x] Desactivar acciones no disponibles explicando el motivo.
- [x] Solicitar confirmación contextual antes de comprar o usar objetos.
- [x] Advertir al reemplazar un Pokémon activo.
- [x] Mostrar una advertencia especial antes de descartar un Shiny.
- [x] Diferenciar visualmente huevos Normal, Uncommon y Rare.
- [x] Mostrar feedback visual después de cada compra o uso.

## Ajustes

- [x] Agrupar opciones en secciones fáciles de recorrer.
- [x] Mantener las opciones técnicas dentro de una sección avanzada plegada.
- [x] Permitir configurar idioma.
- [x] Permitir configurar intervalo de actualización.
- [x] Permitir configurar inicio automático.
- [x] Permitir elegir los elementos visibles en la bandeja.
- [x] Permitir configurar el pet flotante y su tamaño.
- [x] Permitir activar por separado notificaciones de límites y eventos.
- [x] Permitir elegir porcentaje usado o restante.
- [x] Añadir adaptación consistente a temas claro y oscuro.
- [x] Añadir importación y exportación de partida mediante selectores de archivo.

## Pulido transversal

- [x] Definir una jerarquía tipográfica consistente.
- [x] Unificar iconos, márgenes, radios y espaciado.
- [x] Mejorar el comportamiento con escalado DPI.
- [x] Evitar parpadeos y cambios bruscos durante las actualizaciones.
- [x] Diseñar estados de carga, error y desconexión.
- [x] Asegurar navegación por teclado y foco visible.
- [x] Revisar contraste y legibilidad.
- [x] Mantener la interfaz compacta sin sacrificar claridad.

## Registro de entregas

- [x] Auditar la implementación inicial y marcar únicamente requisitos verificables.
- [x] Añadir el pet flotante configurable, persistente y adaptado a cambios de pantalla.
- [x] Separar Bag y Shop y añadir confirmaciones, motivos de bloqueo y feedback inmediato.
- [x] Personalizar el contenido del tooltip de la bandeja y usar el personaje como icono.
- [x] Permitir elegir un representante de la colección sin cambiar el compañero activo.
- [x] Sustituir los límites en texto plano por barras con modo usado/restante y colores de urgencia.
- [x] Completar Home, celebraciones, Pokédex paginada y navegación por proveedor.
- [x] Añadir temas, idioma, umbrales, estados de actualización e importación/exportación segura.
- [x] Ejecutar QA automático, visual y de accesibilidad sobre el roadmap completo.
