package com.personalassistant.companion;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Reads Markdown documents separated by U+001E on stdin and prints Markdown's block and run structure for each, followed by a U+001E line. */
public final class MarkdownProbe {
    private MarkdownProbe(){}
    private static final String[] KINDS={"P","H","CODE","LI","QUOTE","HR","TABLE"};

    public static void main(String[] args)throws Exception{
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;while((n=System.in.read(buffer))>0)bytes.write(buffer,0,n);
        PrintStream out=new PrintStream(System.out,true,"UTF-8");
        for(String doc:new String(bytes.toByteArray(),StandardCharsets.UTF_8).split("\u001e",-1)){StringBuilder b=new StringBuilder();dump(Markdown.parse(doc),"",b);out.print(b);out.println("\u001e");}
    }
    private static void dump(List<Markdown.Block> blocks,String pad,StringBuilder b){
        for(Markdown.Block block:blocks){
            b.append(pad).append(KINDS[block.kind]);
            if(block.kind==Markdown.HEADING||block.kind==Markdown.ITEM)b.append(block.level);
            if(block.marker!=null&&!block.marker.isEmpty())b.append('(').append(block.marker).append(')');
            if(block.open)b.append(" open");
            if(block.kind==Markdown.CODE)b.append(' ').append(block.text.replace("\n","\\n"));
            else if(block.kind==Markdown.TABLE)for(String[] row:block.rows){b.append(" |");for(String cell:row)b.append(' ').append(runs(cell)).append(" |");}
            else if(block.kind!=Markdown.QUOTE&&block.kind!=Markdown.RULE)b.append(' ').append(runs(block.text));
            b.append('\n');
            if(block.children!=null)dump(block.children,pad+"  ",b);
        }
    }
    /** Runs as text, styled ones wrapped as {b,i,c:text} and links as {=url:text}. */
    static String runs(String text){
        StringBuilder b=new StringBuilder();
        for(Markdown.Run run:Markdown.inline(text)){
            String tags=((run.style&Markdown.BOLD)!=0?"b":"")+((run.style&Markdown.ITALIC)!=0?"i":"")+((run.style&Markdown.MONO)!=0?"c":"")+(run.url!=null?"="+run.url:"");
            b.append(tags.isEmpty()?run.text:"{"+tags+":"+run.text+"}");
        }
        return b.toString().replace("\n","\\n");
    }
}
