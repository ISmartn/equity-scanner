import tailwindcss from 'tailwindcss';
import autoprefixer from 'autoprefixer';
import orderFlowScope from './postcss-order-flow-scope.mjs';

export default {
  plugins: [tailwindcss(), autoprefixer(), orderFlowScope()],
};
