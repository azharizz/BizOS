import js from '@eslint/js'
import tseslint from 'typescript-eslint'

const noEffect = 'No useEffect (PRODUCT_RESEARCH 6.4): derive in render, use handlers, TanStack Query, a store or a ref callback.'

export default tseslint.config(js.configs.recommended, ...tseslint.configs.recommended, {
  rules: {
    'no-restricted-syntax': ['error',
      { selector: "CallExpression[callee.name='useEffect']", message: noEffect },
      { selector: "CallExpression[callee.property.name='useEffect']", message: noEffect },
      { selector: "CallExpression[callee.name='useLayoutEffect']", message: noEffect }],
    'no-restricted-imports': ['error', { paths: [{ name: 'react', importNames: ['useEffect', 'useLayoutEffect'], message: noEffect }] }],
  },
})
