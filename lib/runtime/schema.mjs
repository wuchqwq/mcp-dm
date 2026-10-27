// The legacy MCP argument validator. Deliberately preserve its error wording
// and division of work with the scientific workers' cross-field validators.
export class RpcError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
export function tool(name, description, properties, required = []) {
  return {name, description, inputSchema:{type:'object',properties,required,additionalProperties:false}};
}
export function validate(value, schema, label = 'arguments') {
  const types = Array.isArray(schema.type) ? schema.type : [schema.type];
  const matches = types.some(t => t === 'null' ? value === null : t === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value)
    : t === 'array' ? Array.isArray(value)
    : t === 'integer' ? Number.isSafeInteger(value)
    : t === 'number' ? typeof value === 'number' && Number.isFinite(value)
    : typeof value === t);
  if (!matches) throw new RpcError(-32602, `${label}: 类型应为 ${types.join('/')}`);
  if (schema.enum && !schema.enum.includes(value)) throw new RpcError(-32602, `${label}: 不是允许的取值`);
  if (typeof value === 'string' && (value.length < (schema.minLength ?? 0) || value.length > (schema.maxLength ?? Infinity) || (schema.pattern && !new RegExp(schema.pattern).test(value)))) {
    throw new RpcError(-32602, `${label}: 字符串长度或格式错误`);
  }
  if (typeof value === 'number' && ((schema.minimum !== undefined && value < schema.minimum) || (schema.maximum !== undefined && value > schema.maximum))) throw new RpcError(-32602, `${label}: 超出允许范围`);
  if (Array.isArray(value)) {
    if (value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? Infinity)) throw new RpcError(-32602, `${label}: 元素数量错误`);
    value.forEach((v,i)=>validate(v,schema.items,`${label}[${i}]`));
  } else if (value !== null && types.includes('object')) {
    for (const key of schema.required || []) if (!Object.hasOwn(value,key)) throw new RpcError(-32602,`${label}.${key}: 缺少必填参数`);
    for (const key of Object.keys(value)) {
      if (!Object.hasOwn(schema.properties,key)) throw new RpcError(-32602,`${label}.${key}: 未知参数`);
      validate(value[key],schema.properties[key],`${label}.${key}`);
    }
  }
}
