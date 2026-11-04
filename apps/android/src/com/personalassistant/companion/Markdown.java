package com.personalassistant.companion;

import java.util.*;

/**
 * Framework-free Markdown reader for chat answers: lines become blocks, block text becomes styled runs, and RichText turns both into spans.
 * Streaming text is safe at every prefix: an unclosed emphasis, code span or link stays literal and an unclosed fence stays an open code block.
 */
final class Markdown {
    private Markdown(){}
    static final int PARAGRAPH=0,HEADING=1,CODE=2,ITEM=3,QUOTE=4,RULE=5,TABLE=6;
    static final int BOLD=1,ITALIC=2,MONO=4;
    private static final String PUNCT="!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~";

    /** Level is the heading level (1-3) or list depth (0-1); marker is a list marker such as "-" or "3." ("" continues the item above) or a fence's language. */
    static final class Block {
        final int kind,level;final String marker,text;final List<Block> children;final List<String[]> rows;final boolean open;
        Block(int kind,int level,String marker,String text,List<Block> children,List<String[]> rows,boolean open){this.kind=kind;this.level=level;this.marker=marker;this.text=text;this.children=children;this.rows=rows;this.open=open;}
        static Block of(int kind,int level,String marker,String text){return new Block(kind,level,marker,text,null,null,false);}
        boolean ordered(){return marker!=null&&!marker.isEmpty()&&Character.isDigit(marker.charAt(0));}
    }
    /** Text with BOLD, ITALIC and MONO bits; url is set only for http, https and mailto targets. */
    static final class Run {
        final String text;final int style;final String url;
        Run(String text,int style,String url){this.text=text;this.style=style;this.url=url;}
    }

    // ---- blocks ----

    static List<Block> parse(String source){
        String[] lines=(source==null?"":source).replace("\r\n","\n").replace('\r','\n').split("\n",-1);
        List<Block> out=new ArrayList<>();int i=0;
        while(i<lines.length){
            String line=lines[i],t=line.trim();
            if(t.isEmpty()){i++;continue;}
            String fence=fence(t);
            if(fence!=null){
                int indent=indent(line);StringBuilder code=new StringBuilder();boolean closed=false,first=true;
                for(i++;i<lines.length;i++){String l=lines[i];if(closes(l.trim(),fence)){closed=true;i++;break;}if(!first)code.append('\n');first=false;code.append(dedent(l,indent));}
                out.add(new Block(CODE,0,t.substring(fence.length()).trim(),code.toString(),null,null,!closed));continue;
            }
            Block heading=heading(t);
            if(heading!=null){out.add(heading);i++;continue;}
            if(rule(t)){out.add(Block.of(RULE,0,null,""));i++;continue;}
            if(t.startsWith(">")){
                StringBuilder inner=new StringBuilder();
                for(;i<lines.length&&lines[i].trim().startsWith(">");i++){String q=lines[i].trim().substring(1);if(q.startsWith(" "))q=q.substring(1);if(inner.length()>0)inner.append('\n');inner.append(q);}
                out.add(new Block(QUOTE,0,null,"",parse(inner.toString()),null,false));continue;
            }
            String[] item=item(line);
            if(item!=null){
                StringBuilder text=new StringBuilder(item[2]);
                for(i++;i<lines.length&&!lines[i].trim().isEmpty()&&!starts(lines,i);i++)text.append(text.length()>0?" ":"").append(lines[i].trim());
                out.add(Block.of(ITEM,Integer.parseInt(item[0]),item[1],text.toString()));continue;
            }
            if(table(lines,i)){
                List<String[]> rows=new ArrayList<>();rows.add(cells(line));
                for(i+=2;i<lines.length&&lines[i].contains("|")&&!lines[i].trim().isEmpty();i++)rows.add(cells(lines[i]));
                out.add(new Block(TABLE,0,null,"",null,rows,false));continue;
            }
            Block last=out.isEmpty()?null:out.get(out.size()-1);boolean continues=last!=null&&last.kind==ITEM&&indent(line)>=2;
            StringBuilder text=new StringBuilder(t);
            for(i++;i<lines.length&&!lines[i].trim().isEmpty()&&!starts(lines,i);i++)text.append(continues?" ":"\n").append(lines[i].trim());
            out.add(continues?Block.of(ITEM,last.level,"",text.toString()):Block.of(PARAGRAPH,0,null,text.toString()));
        }
        return out;
    }
    /** True when line i opens a block other than a paragraph, which ends the paragraph or list item above it. */
    private static boolean starts(String[] lines,int i){String t=lines[i].trim();return fence(t)!=null||heading(t)!=null||rule(t)||t.startsWith(">")||item(lines[i])!=null||table(lines,i);}
    private static int indent(String line){int n=0;for(int i=0;i<line.length();i++){char c=line.charAt(i);if(c==' ')n++;else if(c=='\t')n+=4;else break;}return n;}
    private static String dedent(String line,int indent){int i=0;while(i<line.length()&&i<indent&&line.charAt(i)==' ')i++;return line.substring(i);}
    private static String fence(String t){
        if(t.length()<3||t.charAt(0)!='`'&&t.charAt(0)!='~')return null;char c=t.charAt(0);int n=0;while(n<t.length()&&t.charAt(n)==c)n++;
        return n<3||c=='`'&&t.indexOf('`',n)>=0?null:t.substring(0,n);
    }
    private static boolean closes(String t,String fence){if(t.length()<fence.length())return false;for(int i=0;i<t.length();i++)if(t.charAt(i)!=fence.charAt(0))return false;return true;}
    private static Block heading(String t){
        int n=0;while(n<t.length()&&t.charAt(n)=='#')n++;
        if(n<1||n>6||n<t.length()&&t.charAt(n)!=' '&&t.charAt(n)!='\t')return null;
        String text=t.substring(n).trim();int end=text.length();while(end>0&&text.charAt(end-1)=='#')end--;
        if(end<text.length()&&(end==0||text.charAt(end-1)==' '))text=text.substring(0,end).trim();
        return Block.of(HEADING,Math.min(n,3),null,text);
    }
    private static boolean rule(String t){
        if(t.length()<3)return false;char c=t.charAt(0);if(c!='-'&&c!='*'&&c!='_')return false;int n=0;
        for(int i=0;i<t.length();i++){char d=t.charAt(i);if(d==c)n++;else if(d!=' '&&d!='\t')return false;}
        return n>=3;
    }
    /** {depth, marker, text} for a list line, or null. */
    private static String[] item(String line){
        int indent=indent(line);String t=line.trim();int n=0;
        if(t.isEmpty())return null;char c=t.charAt(0);
        if(c=='-'||c=='*'||c=='+')n=1;
        else{while(n<t.length()&&n<9&&Character.isDigit(t.charAt(n)))n++;if(n==0||n>=t.length()||t.charAt(n)!='.'&&t.charAt(n)!=')')return null;n++;}
        if(n<t.length()&&t.charAt(n)!=' '&&t.charAt(n)!='\t')return null;
        return new String[]{indent>=2?"1":"0",t.substring(0,n),t.substring(n).trim()};
    }
    private static boolean table(String[] lines,int i){return lines[i].contains("|")&&i+1<lines.length&&delimiter(lines[i+1]);}
    private static boolean delimiter(String line){
        String t=line.trim();if(!t.contains("-"))return false;String[] cells=trimPipes(t).split("\\|",-1);
        for(String cell:cells)if(!cell.trim().matches(":?-+:?"))return false;
        return t.contains("|")||cells.length>1;
    }
    private static String trimPipes(String t){if(t.startsWith("|"))t=t.substring(1);if(t.endsWith("|")&&!t.endsWith("\\|"))t=t.substring(0,t.length()-1);return t;}
    /** Cells split on pipes that are neither escaped nor inside a code span. */
    static String[] cells(String line){
        String t=trimPipes(line.trim());List<String> out=new ArrayList<>();StringBuilder cell=new StringBuilder();boolean code=false;
        for(int i=0;i<t.length();i++){char c=t.charAt(i);
            if(c=='\\'&&i+1<t.length()){cell.append(c).append(t.charAt(++i));continue;}
            if(c=='`')code=!code;
            if(c=='|'&&!code){out.add(cell.toString().trim());cell.setLength(0);}else cell.append(c);}
        out.add(cell.toString().trim());return out.toArray(new String[0]);
    }

    // ---- inline ----

    static List<Run> inline(String s){List<Run> out=new ArrayList<>();if(s!=null)inline(s,0,s.length(),0,null,out);return out;}
    private static void inline(String s,int from,int to,int style,String url,List<Run> out){
        StringBuilder b=new StringBuilder();int i=from;
        while(i<to){char c=s.charAt(i);
            if(c=='\\'&&i+1<to&&PUNCT.indexOf(s.charAt(i+1))>=0){b.append(s.charAt(i+1));i+=2;continue;}
            if(c=='`'){int n=count(s,i,to,c),close=ticks(s,i+n,to,n);
                if(close<0){b.append(s,i,i+n);i+=n;continue;}
                String code=s.substring(i+n,close).replace('\n',' ');if(code.length()>2&&code.startsWith(" ")&&code.endsWith(" ")&&!code.trim().isEmpty())code=code.substring(1,code.length()-1);
                flush(b,style,url,out);add(out,code,style|MONO,url);i=close+n;continue;}
            if(c=='*'||c=='_'){int n=count(s,i,to,c);
                if(n>3){b.append(s,i,i+n);i+=n;continue;}
                if(i+n<to&&!Character.isWhitespace(s.charAt(i+n))&&(c=='*'||i==0||!Character.isLetterOrDigit(s.charAt(i-1)))){int close=closing(s,i+n,to,c,n);
                    if(close>=0){flush(b,style,url,out);inline(s,i+n,close,style|(n==1?ITALIC:n==2?BOLD:BOLD|ITALIC),url,out);i=close+n;continue;}}
                b.append(c);i++;continue;}
            int label=c=='['?i:c=='!'&&i+1<to&&s.charAt(i+1)=='['?i+1:-1;
            if(label>=0){int[] link=link(s,label,to);
                if(link!=null){String target=target(s.substring(link[1]+1,link[2]));flush(b,style,url,out);inline(s,label+1,link[0],style,safe(target)?target:url,out);i=link[2]+1;continue;}
                b.append(s,i,label+1);i=label+1;continue;}
            if(c=='<'){int end=s.indexOf('>',i);
                if(end>0&&end<to){String target=s.substring(i+1,end);if(safe(target)&&!target.contains(" ")){flush(b,style,url,out);add(out,target.startsWith("mailto:")?target.substring(7):target,style,url!=null?url:target);i=end+1;continue;}}}
            if(url==null&&c=='h'&&(s.startsWith("https://",i)||s.startsWith("http://",i))&&(i==0||!Character.isLetterOrDigit(s.charAt(i-1))&&s.charAt(i-1)!='_')){int end=bare(s,i,to);
                if(end>s.indexOf("//",i)+3){flush(b,style,url,out);String found=s.substring(i,end);add(out,found,style,found);i=end;continue;}}
            b.append(c);i++;
        }
        flush(b,style,url,out);
    }
    private static int count(String s,int i,int to,char c){int n=0;while(i+n<to&&s.charAt(i+n)==c)n++;return n;}
    /** Start of the next backtick run of exactly n, or -1. */
    private static int ticks(String s,int from,int to,int n){for(int j=from;j<to;){if(s.charAt(j)=='`'){int m=count(s,j,to,'`');if(m==n)return j;j+=m;}else j++;}return -1;}
    /** Start of the closing run of exactly n delimiters, skipping escapes and code spans, or -1. */
    private static int closing(String s,int from,int to,char c,int n){
        for(int j=from;j<to;){char d=s.charAt(j);
            if(d=='\\'){j+=2;continue;}
            if(d=='`'){int m=count(s,j,to,d),e=ticks(s,j+m,to,m);j=e>=0?e+m:j+m;continue;}
            if(d==c){int m=count(s,j,to,c);if(m==n&&!Character.isWhitespace(s.charAt(j-1))&&(c=='*'||j+m>=to||!Character.isLetterOrDigit(s.charAt(j+m))))return j;j+=m;continue;}
            j++;}
        return -1;
    }
    /** {closing bracket, opening paren, closing paren} of a [label](target), or null. */
    private static int[] link(String s,int open,int to){
        int depth=0,close=-1;
        for(int j=open;j<to&&close<0;j++){char d=s.charAt(j);if(d=='\\'){j++;continue;}if(d=='`'){int m=count(s,j,to,d),e=ticks(s,j+m,to,m);if(e>=0)j=e+m-1;else j+=m-1;continue;}if(d=='[')depth++;else if(d==']'&&--depth==0)close=j;}
        if(close<0||close+1>=to||s.charAt(close+1)!='(')return null;depth=0;
        for(int j=close+1;j<to;j++){char d=s.charAt(j);if(d=='\\'){j++;continue;}if(d=='(')depth++;else if(d==')'&&--depth==0)return new int[]{close,close+1,j};}
        return null;
    }
    private static String target(String inside){String t=inside.trim();if(t.startsWith("<")){int end=t.indexOf('>');return end>0?t.substring(1,end):t;}int space=t.indexOf(' ');return space<0?t:t.substring(0,space);}
    static boolean safe(String url){if(url==null)return false;String u=url.toLowerCase(Locale.ROOT);return u.startsWith("https://")&&u.length()>8||u.startsWith("http://")&&u.length()>7||u.startsWith("mailto:")&&u.length()>7;}
    /** End of a bare URL: trailing sentence punctuation and an unbalanced closing parenthesis stay outside. */
    private static int bare(String s,int i,int to){
        int end=i;while(end<to&&!Character.isWhitespace(s.charAt(end))&&s.charAt(end)!='<')end++;
        while(end>i){char d=s.charAt(end-1);
            if(".,;:!?'\"*_".indexOf(d)>=0){end--;continue;}
            if(d==')'){int open=0,shut=0;for(int j=i;j<end;j++){if(s.charAt(j)=='(')open++;else if(s.charAt(j)==')')shut++;}if(shut>open){end--;continue;}}
            break;}
        return end;
    }
    private static void flush(StringBuilder b,int style,String url,List<Run> out){add(out,b.toString(),style,url);b.setLength(0);}
    private static void add(List<Run> out,String text,int style,String url){
        if(text.isEmpty())return;Run last=out.isEmpty()?null:out.get(out.size()-1);
        if(last!=null&&last.style==style&&Objects.equals(last.url,url))out.set(out.size()-1,new Run(last.text+text,style,url));else out.add(new Run(text,style,url));
    }
}
